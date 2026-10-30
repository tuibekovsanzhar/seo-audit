"""Reconcile only proven per-URL overlap; preserve source observations and separate rules."""
from copy import deepcopy
import re


def get(obj,key,default=None):
    return obj.get(key,default)if isinstance(obj,dict)else getattr(obj,key,default)


def urls(f):
    scope=f.get('scope')or{}
    return list(dict.fromkeys(scope.get('_all_urls')or scope.get('urls')or[]))


def retrieval_urls(f):
    """Only URLs represented by actual IDX1 retrieval findings, not arbitrary IDX1 notes."""
    if f.get('check_id')!='IDX-1' or f.get('severity')=='Info':return set()
    ev=f.get('evidence')or{};title=(ev.get('judgment')or{}).get('source',{}).get('title')or f.get('title','')
    if 'empty page' in title or (ev.get('judgment')or{}).get('kind')=='empty_response':
        out=set(urls(f))
        for row in ev.get('pages')or[]:
            attempts=row.get('attempts')or[]
            if any(a.get('status')==200 and a.get('empty')is False and not a.get('error')for a in attempts):out.discard(row.get('url'))
        return out
    membership = ev.get('retrieval_membership') or {}
    if membership.get('complete') and isinstance(membership.get('urls'),list):
        return set(membership['urls'])
    if 'client error (4xx)' in title:
        evidenced={r['url']for r in ev.get('pages')or[] if isinstance(r.get('status'),int)and 400<=r['status']<600 and not r.get('error')}
        return evidenced
    if 'server error (5xx)' in title or 'connection level on every attempt' in title or 'time out on every attempt' in title:
        return {r['url'] for r in ev.get('pages') or [] if r.get('attempts') and all(a.get('error') or (a.get('status') or 0) >= 500 for a in r['attempts'])}
    if 'show a server error message' in title:return set(urls(f))
    return set()


def _dependent_llms_retrieval(by):
    """Fold only a link judgment explicitly reusing the same native crawl response.

    A separate light/other-client response, changed status or unknown membership
    remains independent. Captured raw findings survive in the check evidence.
    """
    idx, llms = by.get('IDX-1'), by.get('ACC-8')
    if not idx or not llms:
        return
    owners = {}
    for f in idx.get('findings') or []:
        if f.get('confidence') != 'verified':
            continue
        represented = retrieval_urls(f)
        for row in (f.get('evidence') or {}).get('pages') or []:
            if row.get('url') in represented and isinstance(row.get('status'), int) and row['status'] >= 400:
                owners[(row['url'], row['status'])] = f
    for f in list(llms.get('findings') or []):
        ev = f.get('evidence') or {}
        rows = ev.get('not_working') or []
        if not rows or 'lead to pages that do not work' not in f.get('title', ''):
            continue
        matches = [r for r in rows if r.get('source') == 'crawl' and (r.get('url'), r.get('status')) in owners]
        if not matches:
            continue
        overlap = set(r['url'] for r in matches)
        # The complete not_working_urls list is required, not a capped sample.
        bad = (ev.get('links') or {}).get('not_working_urls')
        if not isinstance(bad, list) or len(set(bad)) != (ev.get('links') or {}).get('not_working'):
            continue
        original = deepcopy(f)
        records = llms.setdefault('evidence', {}).setdefault('dependent_retrieval_observations', [])
        if not any(r['finding']['id'] == f['id'] for r in records):
            records.append({'finding': original, 'urls': sorted(overlap), 'source': 'same captured native crawl response'})
        for row in matches:
            owner = owners[(row['url'], row['status'])]
            refs = owner.setdefault('evidence', {}).setdefault('dependent_observations', [])
            if not any(r['finding_id'] == f['id'] and row['url'] in r['urls'] for r in refs):
                refs.append({'finding_id': f['id'], 'check_id': 'ACC-8', 'urls': [row['url']],
                             'file': ev.get('file'), 'status': row['status'], 'source': 'same captured native crawl response'})
        remaining = [u for u in bad if u not in overlap]
        if not remaining:
            llms['findings'].remove(f)
        else:
            ev['not_working'] = [r for r in rows if r.get('url') not in overlap]
            ev['links'] = {**ev['links'], 'not_working': len(remaining), 'not_working_urls': remaining}
            ev['reported_under_idx1'] = {'count': len(overlap), 'urls': sorted(overlap)}
            f['title'] = re.sub(r'^\d+ of ', str(len(remaining)) + ' of ', f['title'])
    if not llms.get('findings') and llms.get('evidence', {}).get('dependent_retrieval_observations'):
        llms['status'] = 'observed'


def reconcile(checks,crawl,states=None,*,sitemaps=True):
    checks=deepcopy(checks);by={c['check_id']:c for c in checks};idx=by.get('IDX-1');rnd=by.get('RND-2')
    _dependent_llms_retrieval(by)
    pages={get(p,'url'):p for p in get(crawl,'pages',[])or[]}
    render=get(get(crawl,'render',{})or{},'pages',{})or{}
    if idx and rnd:
        for f in list(idx.get('findings')or[]):
            if not retrieval_urls(f) or not ('empty page'in f.get('title','')or(f.get('evidence',{}).get('judgment')or{}).get('kind')=='empty_response'):continue
            overlap={}
            for u in urls(f):
                page=pages.get(u);raw=get(page,'analysis',{})or{};entry=render.get(u)or{};view=get(entry,'rendered',{})or{}
                if not((get(page,'body_bytes',0)or 0)>0 and get(page,'status')==200 and entry.get('ok')):continue
                text=raw.get('_visible_text')or'';rich=get(view,'_visible_text','')or''
                raw_words=raw.get('visible_words',len(text.split()));rich_words=get(view,'visible_words',len(rich.split()))
                raw_chars=raw.get('visible_chars',len(text));rich_chars=get(view,'visible_chars',len(rich))
                if raw_words>=10 or rich_words<10 or rich_chars<=raw_chars:continue
                if not (raw.get('external_scripts') or raw.get('inline_script_chars') or re.search(r'<script\b',raw.get('_raw_html')or'',re.I)):continue
                for other in rnd.get('findings')or[]:
                    ev=other.get('evidence')or{}
                    rows=(ev.get('pages')or[])+(ev.get('facts')or[])
                    if u in urls(other) and any(r.get('url')==u and (r.get('headings_only_after_render')or r.get('prices_only_after_render')or'after JavaScript'in r.get('where',''))for r in rows):
                        overlap[u]=other;break
            if not overlap:continue
            saved=deepcopy(f)
            records=idx.setdefault('evidence',{}).setdefault('js_dependency_observations',[])
            if not any(r.get('id')==saved['id']for r in records):records.append(saved)
            for u,other in overlap.items():
                related=other.setdefault('evidence',{}).setdefault('related_retrieval_observations',[])
                if not any(r['url']==u and r['finding_id']==saved['id']for r in related):
                    related.append({'url':u,'finding_id':saved['id'],'finding':saved,'rendered_evidence_reference':'crawl.render.pages['+u+']'})
                other['how_to_fix']='Confirm the rendered-only content for these URLs and provide necessary content in server-rendered or static HTML where appropriate. The recorded small raw response and JavaScript dependency are one actionable issue, not proof that the rendered page is absent.'
            rest=[u for u in urls(f)if u not in overlap]
            if rest:
                f['scope']={**f['scope'],'urls':rest,'count':len(rest)}
                if '_all_urls'in f['scope']:f['scope']['_all_urls']=rest
                f['evidence']['pages']=[r for r in f['evidence'].get('pages')or[] if r.get('url')in rest]
                f['evidence']['unique_affected_urls']=len(rest)
                if f['evidence'].get('observation_strength')=='repeated_empty':f['evidence']['repeated_empty_urls']=len(rest)
                if 'homepage_or_key_page'in f['evidence']:f['evidence']['homepage_or_key_page']=[u for u in f['evidence']['homepage_or_key_page']if u in rest]
                f['title']=re.sub(r'^\d+',str(len(rest)),f['title'])
                old=(f['evidence'].get('judgment')or{}).get('source')
                if old:old.update(title=f['title'],scope=deepcopy(f['scope']))
            else:idx['findings'].remove(f)
        if not idx.get('findings') and idx.get('evidence',{}).get('js_dependency_observations'):idx['status']='observed'
    if sitemaps and idx and by.get('IDX-5'):
        represented=set().union(*(retrieval_urls(f)for f in idx.get('findings')or[])) if idx.get('findings')else set()
        for f in list(by['IDX-5'].get('findings')or[]):
            ev=f.get('evidence')or{};known=states or ev.get('sitemap_decisions')or[]
            if not('are not live, indexable pages'in f.get('title','')or(ev.get('judgment')or{}).get('kind')=='sitemap_review'):continue
            eligible={'error_response','repeated_empty','uncorroborated_empty'}
            overlap=[r['url']for r in known if r.get('url')in represented and r['state']in eligible]
            review=[r['url']for r in known if r['state']in eligible|{'redirect_observed','noindex_observed','contradictory'}]
            if not known:
                from .evidence_accuracy import membership
                review,complete=membership(f)
                ev['membership_assessment']={'known_urls':review,'complete':complete,'declared_count':f.get('scope',{}).get('count')}
                if not complete:
                    ev['overlap_unassessed']='Complete URL membership was not retained; exact overlap and remaining counts are unassessed.'
                    continue
                overlap=[u for u in review if u in represented]
            if not overlap:continue
            ev['reported_under_idx1']={'count':len(set(overlap)),'examples':list(dict.fromkeys(overlap)), 'why':'Retrieval evidence is represented under IDX-1; sitemap membership remains recorded, not an independent repair.'}
            ev['total_review_scope']={'count':len(set(review)),'urls':list(dict.fromkeys(review))}
            ev['separately_actionable_urls']=[u for u in dict.fromkeys(review)if u not in overlap]
            f['evidence']=ev
            if not ev['separately_actionable_urls']:
                by['IDX-5'].setdefault('evidence',{})['retrieval_overlap']={'finding':deepcopy(f),'reported_under_idx1':ev['reported_under_idx1']}
                by['IDX-5']['findings'].remove(f)
                if not by['IDX-5']['findings']:by['IDX-5']['status']='observed'
    return checks


def objects(checks,crawl,*,sitemaps=True):
    from .models import Confidence
    from .findings import Severity
    from dataclasses import fields,is_dataclass
    from enum import Enum
    def internal(value):
        # Public JSON intentionally strips _all_urls; internal reconciliation must not.
        if is_dataclass(value):return {f.name:internal(getattr(value,f.name))for f in fields(value)}
        if isinstance(value,Enum):return value.value
        if isinstance(value,dict):return {k:internal(v)for k,v in value.items()}
        if isinstance(value,(list,tuple,set)):return [internal(v)for v in value]
        return value
    rows=reconcile(internal(checks),crawl,sitemaps=sitemaps)
    for check,row in zip(checks,rows):
        prior={f.id:f for f in check.findings};new=[]
        for r in row['findings']:
            f=prior[r['id']]
            for k,v in r.items():
                if k=='severity':v=Severity(v)
                if k=='confidence':v=Confidence(v)
                setattr(f,k,v)
            new.append(f)
        check.findings=new;check.evidence=row.get('evidence',{});check.status=row['status']
    return checks
