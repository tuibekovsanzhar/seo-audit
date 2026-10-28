"""Bounded reassessment of the requested new evidence rules, using saved records only.

Does not recollect pages or rewrite source evidence. Old incomplete naming records remain gaps.
"""
from copy import deepcopy
from types import SimpleNamespace as NS


def saved_pages(crawl):
    pages=[]
    for raw in crawl.get('pages')or[]:
        if not isinstance(raw,dict):continue
        data=deepcopy(raw);data.setdefault('headers',{});data.setdefault('depth',1)
        data.setdefault('requested_at',None);data.setdefault('content_type','text/html');data.setdefault('content_checks_eligible',False)
        p=NS(**data)
        p.readable_document=lambda d=data:bool(d.get('status')==200 and d.get('analysis') and not d['analysis'].get('empty_response') and d.get('fetch_class','ok')=='ok')
        pages.append(p)
    return pages


def apply(report):
    from .models import to_jsonable
    from .checks.render import rnd4_non_text
    from .checks.structure import str7_alt
    from .config import CrawlConfig
    crawl=report.get('crawl')or{};pages=saved_pages(crawl)
    complete=[p for p in pages if p.readable_document() and all(k in p.analysis for k in('images','iframes','canvases','pdf_links','has_main_region'))]
    r=NS(origin=crawl.get('origin')or'',start_url=crawl.get('start_url')or crawl.get('origin')or'',pages=complete,render=None)
    for c in report.get('checks')or[]:
        found=[]
        if c['check_id']=='RND-4' and complete:
            check=rnd4_non_text(r,CrawlConfig());found=[to_jsonable(f)for f in check.findings if 'accessible name'in f.title]
            unknown=check.evidence.get('iframe_names_unassessed')or[]
            if unknown:c.setdefault('evidence',{})['iframe_names_unassessed']=unknown
        elif c['check_id']=='STR-7' and complete:
            # str7 with data=None only evaluates captured observations; it never fetches a file.
            check=str7_alt(r,CrawlConfig(),complete,set(),set())
            found=[to_jsonable(f)for f in check.findings if 'placeholder alt text'in f.title]
        if found:
            old={f['id']for f in c.get('findings')or[]}
            added=[f for f in found if f['id']not in old]
            for f in added:
                ev=f['evidence'];rows=ev.get('images')or ev.get('items')or[]
                ev['source_collection_times']=sorted({str(row.get('observed_at')or row.get('requested_at'))for row in rows if row.get('observed_at')or row.get('requested_at')})
                ev['reassessment_processing_time']=f.get('observed_at')
            c['findings']=[*c.get('findings',[]),*added]
            if added:
                c.setdefault('evidence',{}).setdefault('prior_reassessment_summary',c.get('summary'))
                c['summary']=f'{len(c["findings"])} finding(s) after saved-evidence reassessment; no new website observations collected.'
            c['status']='findings'
    _partial_names(report,pages)
    return report


def _partial_names(report,pages):
    """Reuse the normal relevance pipeline, retaining every non-targeted saved assessment."""
    from .dataforseo import insights as i
    from urllib.parse import urlsplit
    brand=report.get('brand')or{};name=brand.get('name')if isinstance(brand,dict)else None
    own=i._tokens(name)
    if len(own)<2:return
    section=report.get('dataforseo')or{};origin=(report.get('crawl')or{}).get('origin')or''
    domain=urlsplit(origin).hostname or origin
    corpus=[p.analysis.get('title')or''for p in pages if getattr(p,'analysis',None)]
    for c in section.get('checks')or[]:
        data=(c.get('evidence')or{}).get('data')or{}
        records=data.get('keyword_assessments')or[]
        if not (data.get('provider_table')or{}).get('rows'):continue
        target=lambda a: len(i._tokens(a.get('keyword')))==1 and i._tokens(a.get('keyword'))[0]in own and not any(s.get('source')=='owner profile'for s in a.get('sources')or[])
        if not any(target(a)for a in records):continue
        retained={(a.get('keyword'),a.get('ranking_url')):deepcopy(a)for a in records if not target(a)}
        work={'checks':[deepcopy(c)]}
        i.refresh_relevance(work)
        i.apply_relevance(work,brand=name,brand_info=brand,domain=domain,texts=corpus,pages=pages,retained_assessments=retained)
        new=work['checks'][0]
        new.setdefault('evidence',{}).setdefault('prior_partial_identity_assessments',[deepcopy(a)for a in records if target(a)])
        new['evidence'].setdefault('prior_relevance_summary',c.get('summary'))
        c.update(new)
