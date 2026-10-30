"""Pure evidence-to-decision qualification shared by new reports and explicit reanalyses.

Open evidence.judgment records decisions; raw observations and stable finding IDs are retained.
This is bounded structural validation, never semantic truth or a new live verification.
"""
from copy import deepcopy
from collections import Counter

VERSION = 'judgment-v1'
LANGUAGE_SUMMARY = 'No language or assessed hreflang problem found. This does not establish that hreflang annotations exist or are required.'
HEAD_TITLE = '{n} external destination(s) have HEAD errors; GET navigation is unverified'
HEAD_ACTION = 'Corroborate the recorded HEAD response with a bounded, guarded GET using the same URL and client. Update or remove a link only if destination failure is corroborated.'
SITEMAP_ACTION = 'Review the per-URL sitemap decisions. Corroborate single empty responses before changing URLs. Reuse IDX-1 retrieval evidence for repeated failures. Confirm intended indexing with the owner before changing noindex or sitemap inclusion; follow redirects to assess their destinations.'
EMPTY_ACTION = 'Reproduce the recorded GET response for the same URL and client, then establish intended content and affected users. Choose a repair only after corroboration; do not remove a URL or change indexability on a single empty response.'
GENERIC_ACTION = 'Inspect each recorded generic link with its accessible name and surrounding text. Change wording only where the destination or purpose is unclear in context; retain useful distinct destinations.'
THIN_ACTION = 'Review whether each page answers its intended purpose. A short form, branch or utility page may be complete. Add missing information only when established; consolidation or noindex requires a separate purpose/content and owner decision.'
DUPLICATE_ACTION = 'Compare purpose, substantive content, audiences and destinations of each group. Keep distinct useful pages. Consolidate or change canonical/indexing only after equivalent purpose and content are established and the owner approves.'
VERIFY = 'Check the same affected URLs, client and property; record method, status/content, observation time and evidence. A report export or owner approval is not verification.'


def _get(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def sitemap_states(crawl):
    """Mutually exclusive per-URL native evidence states. No request or inferred owner intent."""
    from .index_data import row_kind
    from .directives import noindex_directives
    from .urls import non_page_kind
    pages = {_get(p,'url'):p for p in _get(crawl,'pages',[]) or []}
    index = _get(crawl,'index',{}) or {}; check = _get(index,'sitemap_check',{}) or {}
    light = {_get(r,'url'):r for r in _get(check,'rows',[]) or []}
    refetches = {_get(r,'url'):_get(r,'refetch',{}) for r in _get(index,'refetches',[]) or []}
    out=[]
    for url in dict.fromkeys(_get(crawl,'sitemap_urls',[]) or []):
        attempts=[]
        for source, row in [('native_crawl',pages.get(url)),('sitemap_probe',light.get(url)),('idx_refetch',refetches.get(url))]:
            if not row: continue
            analysis=_get(row,'analysis',{}) or {}; headers=_get(row,'headers',{}) or {}
            fc=_get(row,'fetch_class'); fc=getattr(fc,'value',fc)
            empty=bool(_get(row,'empty',False) or _get(row,'empty_response',False) or _get(analysis,'empty_response',False))
            body=_get(row,'body_bytes',_get(row,'bytes'))
            if _get(row,'status')==200 and body==0: empty=True
            noindex=_get(row,'noindex') or noindex_directives({**analysis, 'meta': analysis.get('meta',[])},headers)
            a={'url':url,'source':source,'method':_get(row,'method','GET'),'method_basis':'saved method or documented native GET collector',
               'requested_at':_get(row,'requested_at'),'status':_get(row,'status'),'error':_get(row,'error'),
               'body_bytes':body,'empty':empty,'fetch_class':fc,'noindex':noindex,
               'location':_get(row,'location',_get(row,'redirect_location')),'canonical':_get(row,'canonical')}
            a['kind']=row_kind(a);attempts.append(a)
        kinds={a['kind'] for a in attempts if a['kind'] not in ('blocked','no_answer')}
        empties=[a for a in attempts if a['kind']=='empty' and not a['error']]
        distinct={a['requested_at']for a in empties if a['requested_at']}
        if non_page_kind(url): state='non_page_resource'
        elif not kinds or all(a['status']==200 and a['body_bytes'] is None and not _get(pages.get(url),'analysis') for a in attempts): state='unknown'
        elif len(kinds)>1: state='contradictory'
        elif 'empty'in kinds: state='repeated_empty' if len(distinct)>=2 else 'uncorroborated_empty'
        elif 'noindex'in kinds: state='noindex_observed'
        elif 'redirect'in kinds: state='redirect_observed'
        elif kinds & {'not_found','server_error'}:state='error_response'
        else:state='live_observed' if 'live'in kinds else 'canonical_elsewhere'
        if state=='noindex_observed': action='Owner decision: confirm whether exclusion is intentional. If indexing is required, resolve noindex; otherwise reconcile sitemap inclusion without changing the intended policy.'
        elif state=='uncorroborated_empty':action='Corroborate the empty GET before changing content, links or sitemap inclusion.'
        elif state=='repeated_empty':action='Investigate repeated empty GETs within the recorded client/time scope; use IDX-1 evidence, not a second independent repair.'
        elif state=='redirect_observed':action='Inspect recorded Location and final destination/indexability before replacing the sitemap URL.'
        elif state=='error_response':action='Recheck the recorded error; restore an intended page or update its references after confirming purpose.'
        elif state in ('unknown','contradictory'):action='Evidence is missing or mixed; corroborate before changing the URL.'
        else:action='No removal decision established by this record.'
        out.append({'url':url,'state':state,'attempts':attempts,'action':action,'owner_indexing_requirement':'not_recorded'})
    return out


def qualify(finding, *, sitemap=None):
    """An immutable projection. Never promotes estimated evidence or review to live verification."""
    f=deepcopy(finding)
    if not isinstance(f.get('evidence'),dict): f['evidence']={}
    ev=f['evidence'];has_evidence=any(k!='judgment' for k in ev);old=ev.get('judgment') or {};cid=f.get('check_id')
    source=old.get('source') or {'title':f.get('title',''),'how_to_fix':f.get('how_to_fix',''),'confidence':f.get('confidence'), 'scope':deepcopy(f.get('scope') or {})}
    title=source['title'];action=source['how_to_fix'];status='recorded_observation'
    interpretation='The recorded property is scoped to the supplied evidence; broader impact and cause require separate support.'
    alternatives=['Intent, client behavior, sampling and missing context may change the interpretation.']
    from .recommendation_catalog import note
    estimate=note(cid,title)
    owner,effort=estimate['owner'],estimate['effort'];decision=False
    empty_case=cid=='IDX-1' and ('empty page' in title or old.get('kind')=='empty_response')
    sitemap_case=cid=='IDX-5' and ('are not live, indexable pages' in title or old.get('kind')=='sitemap_review')
    if cid=='IDX-6' and ev.get('links'):
        links=ev['links'];weak=[r for r in links if r.get('method')=='HEAD' and r.get('status')in(404,410) and not any(
            a.get('method')=='GET' and a.get('status')in(404,410) and not a.get('error') for a in r.get('attempts')or[])]
        if weak:
            title=HEAD_TITLE.format(n=len(weak));action=HEAD_ACTION;status='diagnostic_concern';owner,effort='content','S'
            interpretation='HEAD failed in the saved request. A removed destination or broken normal GET navigation is not established.'
            alternatives=['HEAD-specific handling, temporary failure or different client behavior; no historical GET corroboration.']
        elif any((r.get('method')=='GET'and r.get('status')in(404,410)) or any(a.get('method')=='GET'and a.get('status')in(404,410)and not a.get('error') for a in r.get('attempts')or[]) for r in links):
            status='confirmed_within_tested_scope';owner,effort='content','S'
            interpretation='The saved GET returned an error within its recorded client/time scope. Persistent deletion and other visitors were not measured.'
            action='Verify the recorded GET error and intended destination; correct the source link or restore an intended resource when supported. Do not infer a universal or permanent failure.'

        get_attempts=[a for r in links for a in ([r] + list(r.get('attempts') or [])) if a.get('method')=='GET' and not a.get('error')]
        success=any(isinstance(a.get('status'),int)and 200<=a['status']<300 for a in get_attempts)
        if success:
            title=f'{len(links)} external destination(s) have mixed HEAD/GET evidence; review request context'
            status='contradictory_evidence';action=HEAD_ACTION
            interpretation='A successful GET status coexists with saved error evidence. Neither universal failure nor universal success is established; inspect response content and client/time context.'
    if empty_case:
        strength=ev.get('observation_strength');status='confirmed_within_tested_scope'if strength=='repeated_empty'else'diagnostic_concern'
        n=ev.get('unique_affected_urls') or (f.get('scope')or{}).get('count',0)
        title=f'{n} URL(s) returned '+('repeated empty GET responses in the tested client'if strength=='repeated_empty'else'an empty response; persistence is unconfirmed')
        action=EMPTY_ACTION;owner,effort='developer','M'
        interpretation='Empty responses are retrieval observations for the recorded client and time, not proof of universal breakage or a server cause.'
        alternatives=['An intentionally empty/utility endpoint, client-specific response or intermittent failure; intended content is not established.']
    if sitemap_case:
        states=sitemap or ev.get('sitemap_decisions',[])
        if states:ev['sitemap_decisions']=deepcopy(states)
        if states:
            review_urls=list(dict.fromkeys(r['url'] for r in states if r['state'] in (
                'error_response','redirect_observed','noindex_observed','repeated_empty','uncorroborated_empty','contradictory')))
            source.setdefault('scope',deepcopy(f.get('scope') or {}))
            ev['total_review_scope']={'count':len(review_urls),'urls':review_urls}
            actionable=ev.get('separately_actionable_urls',review_urls)
            f['scope']={**(f.get('scope') or {}),'count':len(actionable),'urls':actionable}
            if '_all_urls' in f['scope']:f['scope']['_all_urls']=actionable
        counts=dict(Counter(r['state']for r in states));ev['sitemap_state_counts']=counts
        assessed=ev.get('listed_urls_assessed');observed=sum(v for k,v in counts.items()if k in('error_response','redirect_observed','noindex_observed','repeated_empty','uncorroborated_empty','contradictory'))
        if not states:observed=sum((ev.get('breakdown',{}).get('not_live')or{}).values())or(f.get('scope')or{}).get('count',0)
        title=f'{observed} sitemap URL observation(s) require differentiated review ({assessed if assessed is not None else "unknown"} checked)'
        overlap=(ev.get('reported_under_idx1')or{}).get('count',0)
        if overlap:title+=f'; {overlap} already have IDX-1 retrieval evidence'
        action=SITEMAP_ACTION;owner,effort='seo','M';status='diagnostic_concern';decision=True
        interpretation='Sitemap eligibility depends on the per-URL response, redirect and intended indexing. The combined review count is not a count of proven removed pages.'
        alternatives=['Intentional noindex, legitimate redirection, transient/one-probe emptiness, or a real retrieval failure.']
    if cid=='RND-2' and ev.get('related_retrieval_observations'):
        action='Confirm the rendered-only content for these URLs and provide necessary content in server-rendered or static HTML where appropriate. The recorded small raw response and JavaScript dependency are one actionable issue, not proof that the rendered page is absent.'
    if cid=='STR-14' and ('generic text'in title or 'generic-text'in title):
        ev['link_observation_kind']='generic_text'
        from .report import finding_counts
        n=finding_counts(f).get('occurrences')
        if n is not None: title=f'{n} generic-text link occurrence(s) recorded; purpose requires contextual review'
        shared=ev.get('shared_element') or {}
        targets=list(dict.fromkeys(str(r.get('target') or r.get('href')) for r in ev.get('links') or [] if r.get('target') or r.get('href')))
        if shared.get('target') and shared['target'] not in targets:targets.append(str(shared['target']))
        texts=[]
        for r in ev.get('links') or []:
            values=r.get('texts') or ([r['text']] if r.get('text') else [])
            if isinstance(values,dict):values=list(values)
            for v in values:
                text=v if isinstance(v,str) else v.get('text') if isinstance(v,dict) else None
                if text and text not in texts:texts.append(text)
        if not texts and ': ' in source['title']:texts=[source['title'].rsplit(': ',1)[1]]
        # A headline identifies the group; it is not the exhaustive target appendix.
        # Keep all original target records, and explicitly show additional membership.
        target_label=(targets[0]+(f' … (+{len(targets)-1})'if len(targets)>1 else''))if targets else''
        identity='; '.join(filter(None,[str(shared.get('container') or shared.get('selector') or ''), ' / '.join(texts), target_label]))
        if identity:title+=' — '+identity
        status='diagnostic_concern';action=GENERIC_ACTION;owner,effort='content','S'
        interpretation='Generic anchor wording is recorded. Whether its purpose is unclear depends on accessible name and surrounding context; no ranking penalty is measured.'
        alternatives=['Equivalent nearby text or a useful distinct related-post destination may make the purpose clear.']
    if cid=='STR-15':
        status='diagnostic_concern';action=THIN_ACTION;owner,effort='content','M';decision=True
        interpretation='A word-count threshold measures length, not whether the page fulfils its purpose.'
    if cid=='IDX-8':
        action=DUPLICATE_ACTION;status='diagnostic_concern';owner,effort='seo','M';decision=True
        interpretation='Text similarity does not establish identical business purpose or justify page consolidation.'
    if cid=='STR-2' and ('no subheadings'in title or 'more than one <h1>'in title):
        status='diagnostic_concern';owner,effort='content','M'
        action='Review the reading outline and content structure. Tables and lists may already structure the information; add meaningful headings where they improve navigation. Heading levels alone do not prove a ranking or accessibility failure.'
        interpretation='Heading structure is measured; usability requires context, not a threshold alone.'
    if cid=='ACC-3' and ('noindex' in title.lower() or 'no-snippet' in title.lower() or 'nosnippet' in title.lower()):
        status='intentional_configuration' if f.get('intent') else 'owner_context_required'
        decision=not bool(f.get('intent'))
        from .evidence_accuracy import NOINDEX_ACTION
        if 'noindex' in title.lower():action=NOINDEX_ACTION
        interpretation='The directive is observed. Whether exclusion is intended or indexing is required is an owner decision; a noindex declaration is not a missing page.'
    if cid=='STR-7' and ('offered in WebP or AVIF' in title or 'delivery assessed separately' in title):
        from .evidence_accuracy import FORMAT_ACTION, FORMAT_EXPECTED
        f["expected"] = FORMAT_EXPECTED
        a=ev.get('format_assessment')or{}
        n=a.get('occurrences',ev.get('images'))
        modern=a.get('markup_modern_occurrences',ev.get('with_webp_or_avif'))
        if isinstance(n,int) and isinstance(modern,int):
            title=f'{modern} of {n} image occurrence(s) reference WebP or AVIF in markup; delivery assessed separately'
        else:
            title='Image-format markup observations; WebP or AVIF delivery is unassessed'
        action=FORMAT_ACTION;status='informational_observation'
        if all(isinstance(a.get(k),int)for k in ('occurrences','unique_resources','response_resources_assessed','delivery_unassessed_resources')):
            note=f"Retained image-format scope: {a['occurrences']} occurrences, {a['unique_resources']} resources; {a['response_resources_assessed']} resources with recorded response MIME, {a['delivery_unassessed_resources']} without it. Unobserved delivery alternatives remain unassessed."
            f['notes']=[v for v in f.get('notes',[])if not v.startswith('Retained image-format scope: ')] + [note]
            if a.get('response_formats'):
                note='Recorded response MIME observations: '+', '.join(k+'='+str(v) for k,v in sorted(a['response_formats'].items()))+'. Byte sizes, quality and negotiation may be unavailable.'
                f['notes']=[v for v in f['notes']if not v.startswith('Recorded response MIME observations: ')] + [note]
        interpretation='Markup format references and response MIME observations have different scopes. Missing response evidence cannot establish delivered format, negotiation, quality or savings.'
    if cid=='STR-2' and ('no <h1>'in title or 'no meaningful <h1>'in title):
        rows=ev.get('heading_assessments')or[]
        # Old parsers discarded empty headings; an absent saved entry is not proof of no element.
        if not rows or any(r.get('state')in ('empty','no_meaningful_text_observed')for r in rows):
            title=title.replace('no <h1>', 'no meaningful <h1> text')
            action='Inspect the source HTML and heading tree. Fill an existing empty H1 with the page topic; add a meaningful H1 only where no H1 element exists. Legacy extracts may omit empty elements.'
            interpretation='No meaningful H1 text was captured. An absent heading element and an empty element are distinct; legacy evidence may not distinguish them.'
    if cid=='RND-7' and ('no <main>'in title or 'text in the main content'in title):
        status='informational_observation'
        action='Inspect the measured content boundaries and existing native or ARIA landmarks. Low content ratio or an absent main/article tag alone does not establish missing semantics. Change markup only if equivalent structure is actually absent and needed.'
        interpretation='The recorded structural property is not a measured ranking penalty or proof of an inaccessible page. Equivalent landmarks and page purpose require separate assessment.'
    if cid=='STR-6' and ev.get('signal')=='Last-Modified header':
        status='diagnostic_concern'
        interpretation='Same-day Last-Modified values are an HTTP date pattern, not proof of incorrect edit dates or their cause.'
    if not has_evidence:
        status='not_assessed';f['confidence']='not_assessed';decision=True
        title='Source conclusion unassessed: evidence unavailable'
        interpretation='No supporting observations were saved; a substantive conclusion or consequential repair is not established.'
        action='Recover saved evidence and confirm page purpose with the owner before selecting a repair. Missing evidence does not establish a defect or recovery.'
    # PRF observations use an integer attempt count; IDX observations use request records.
    records = lambda value: [r for r in value if isinstance(r, dict)] if isinstance(value, (list, tuple)) else []
    observation_times=sorted({str(a.get('requested_at') or a.get('observed_at')) for key in ('pages','links') for r in records(ev.get(key)) for a in [r]+records(r.get('attempts')) if a.get('requested_at') or a.get('observed_at')})
    qualified=title!=source['title'] or action!=source['how_to_fix'] or status!='recorded_observation'
    # The exact old output is preserved under source, not restated as a measurement.
    observation = title
    if cid == 'IDX-6' and ev.get('links'):
        requests = [a for r in records(ev['links']) for a in [r]+records(r.get('attempts'))]
        responses = Counter(str(a.get('method') or 'method unavailable')+' '+str(a.get('status') if a.get('status') is not None else 'status unavailable') for a in requests)
        observation = str(len(ev['links']))+' saved external-destination record(s); request observations: '+', '.join(k+' × '+str(v) for k,v in sorted(responses.items()))+'. Exact targets, times and attempts remain in evidence.links.'
    elif sitemap_case:
        observation = str(len(states))+' unique listed URL evidence states: '+', '.join(k+'='+str(v) for k,v in sorted(counts.items())) if states else 'Per-URL sitemap evidence unavailable; only the historical aggregate is retained.'
    elif empty_case:
        observation = str(n)+' distinct URLs with recorded empty responses; corroboration: '+str(strength or 'not recorded')+'. Methods and times remain in evidence.pages.'
    elif ev.get('link_observation_kind') == 'generic_text':
        observation = str(n)+' qualifying generic-text DOM occurrences on '+str((f.get('scope')or{}).get('count','unknown'))+' affected pages; total anchors are a separate measurement.'
    if not has_evidence:
        observation = 'No supporting observations were saved.'
    kind='sitemap_review'if sitemap_case else'empty_response'if empty_case else cid
    j={'version':VERSION,'kind':kind,'qualified':qualified,'source':source,'status':status,'observation':observation,
       'interpretation':interpretation,'confidence':f.get('confidence'),'verification_status':'recorded_evidence_only',
       'scope':deepcopy(f.get('scope')or{}),'evidence_reference':f"checks/{cid}/findings/{f.get('id')}/evidence",
       'finding_recorded_at':f.get('observed_at'),'source_observation_times':observation_times,'alternatives':alternatives,
       'action':{'text':action,'priority':{'severity':f.get('severity'),'importance_tier':f.get('importance_tier',2)},'owner':owner,'effort':effort,'estimates':True,'requires_owner_or_evidence_decision':decision,'verification':VERIFY}}
    ev['judgment']=j;f['title']=title;f['how_to_fix']=action
    return f


def header_provenance(finding, pages):
    """Attribute HTTP fields from saved response identity, independently of merged content."""
    f=deepcopy(finding);ev=f.get('evidence') or {}
    if f.get('check_id')!='STR-6' or ev.get('signal')!='Last-Modified header':return f
    scope=set((f.get('scope') or {}).get('urls') or [])
    observations=[]
    for p in pages or []:
        if _get(p,'url') not in scope:continue
        headers=_get(p,'headers',{}) or {};value=headers.get('last-modified')
        if not value:continue
        content=(_get(p,'analysis',{}) or {}).get('content_observation') or {}
        ua=_get(p,'user_agent','') or ''
        native=bool(content.get('native_requested_at') or ua.startswith('Maya-Audit'))
        reader='native_crawl' if native else 'firecrawl' if 'firecrawl' in ua.lower() else 'unknown'
        observations.append({'url':_get(p,'url'),'field':'Last-Modified','value':value,'source':reader,
            'client':ua or None,'observed_at':content.get('native_requested_at') if native and content.get('native_requested_at') else _get(p,'requested_at')})
    if observations:
        sources={r['source'] for r in observations}
        ev.setdefault('original_source_label',deepcopy(ev.get('source')))
        ev['header_observations']=observations
        ev['source']={'reader':next(iter(sources)) if len(sources)==1 else 'mixed',
                      'why':'HTTP response headers; content-reader provenance is separate'}
        f['notes']=[n for n in f.get('notes',[]) if not n.startswith('Source: Firecrawl')]
    f['evidence']=ev
    return f


def qualify_report(report, affected=None):
    """Explicit copied reassessment; source stays immutable. Normal generation uses the same qualifier."""
    r=deepcopy(report)
    for c in r.get('checks',[]):
        for f in c.get('findings',[]):
            full=(affected or {}).get(f['id']);scope=f.get('scope')or{}
            if isinstance(full,list) and len(full)==scope.get('count') and set(scope.get('urls')or[]).issubset(full):
                scope['_all_urls']=deepcopy(full)
    from .evidence_reassessment import apply as reassess_scope
    reassess_scope(r)
    from .reassess_nine import apply as reassess
    reassess(r)
    from .brand import reassess_report as reassess_identity
    reassess_identity(r)
    states=sitemap_states(r.get('crawl')or{})
    from .related_evidence import reconcile
    r['checks']=reconcile(r.get('checks',[]),r.get('crawl')or{},states)
    from .coverage import derive
    for c in r.get('checks',[]):
        from .evidence_accuracy import refresh_check_scope
        refresh_check_scope(c)
        if c.get('check_id')=='STR-9':
            c['summary']=c.get('summary','').replace('Language declarations are present and hreflang links are reciprocal.',LANGUAGE_SUMMARY)
        c['findings']=[qualify(header_provenance(f,(r.get('crawl') or {}).get('pages')),sitemap=states)for f in c.get('findings',[])]
        if c.get('check_id') in ('STR-7','RND-4','IDX-5'):
            gaps=derive(c['check_id'],c['status'],c.get('evidence')or{},c.get('observations')or[])['not_assessed']
            old=(c.setdefault('coverage',{})).get('not_assessed')or[]
            c['coverage']['not_assessed']=old+[g for g in gaps if g['part']not in {x['part']for x in old}]
            if gaps and c['status']=='pass':c['status']='partial'
    from .dataforseo.insights import qualify_section
    if r.get('dataforseo'):r['dataforseo']=qualify_section(r['dataforseo'])
    from .severity import apply as apply_severity
    apply_severity(r.get('checks', []), r.get('crawl') or {})
    from .rules import assign as assign_rules
    assign_rules(r.get('checks', []) + (r.get('answer_engine_panel') or []))
    from .facts import attach as attach_facts
    attach_facts(r.get('checks', []) + (r.get('answer_engine_panel') or []))
    # Reconciliation can remove an overlapping finding or add a newly assessed one.
    # Use the ordinary engine ordering; never leave removed IDs in the saved index.
    from types import SimpleNamespace
    from .findings import priority_key, Severity
    from .models import Confidence
    remaining=[f for c in r.get('checks',[])for f in c.get('findings',[])]
    def key(f):
        return priority_key(SimpleNamespace(check_id=f['check_id'],severity=Severity(f['severity']),
            importance_tier=f.get('importance_tier',2),scope=f.get('scope')or{},confidence=Confidence(f.get('confidence','inferred')),
            launch_gated=f.get('launch_gated')or[]))
    r['findings_in_priority_order']=[f['id']for f in sorted(remaining,key=key)]
    qualified_affected=deepcopy(affected or {})
    for f in remaining:
        scope=f.get('scope')or{};known=scope.get('_all_urls')or scope.get('urls')or[]
        if len(known)==scope.get('count'):
            qualified_affected[f['id']]=list(known)
    from .reanalysis import refresh_metrics
    return refresh_metrics(r, qualified_affected)


def qualify_checks(checks, result):
    from .models import to_jsonable
    from .coverage import derive
    copied=deepcopy(checks);states=sitemap_states(result)
    from .related_evidence import objects
    objects(copied,result)
    for c in copied:
        for f in c.findings:
            q=qualify(header_provenance(to_jsonable(f),_get(result,'pages')),sitemap=states)
            from .models import Confidence
            f.title=q['title'];f.how_to_fix=q['how_to_fix'];f.expected=q.get('expected',f.expected);f.evidence=q['evidence'];f.confidence=Confidence(q['confidence']);f.notes=q.get('notes',[])
            prior=deepcopy(f.scope)
            f.scope=deepcopy(q['scope'])
            if prior.get('_all_urls') and f.scope.get('count')==prior.get('count') and set(f.scope.get('urls')or[]).issubset(prior['_all_urls']):
                f.scope['_all_urls']=prior['_all_urls']
            elif q.get('evidence',{}).get('separately_actionable_urls') is not None:
                f.scope['_all_urls']=list(q['evidence']['separately_actionable_urls'])
        if c.check_id=='STR-7':
            gaps=derive(c.check_id,c.status,c.evidence,c.observations)['not_assessed']
            old=c.coverage.get('not_assessed')or[];c.coverage['not_assessed']=old+[g for g in gaps if g['part']not in{x['part']for x in old}];c.settle_status()
    from .severity import apply as apply_severity
    from .rules import assign as assign_rules
    checked = apply_severity(copied, result)
    assign_rules(checked)
    return checked
