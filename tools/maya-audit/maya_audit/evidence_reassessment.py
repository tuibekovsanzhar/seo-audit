"""Reinterpret captured evidence with shared rules; never fetch or rewrite source records."""
from copy import deepcopy
from types import SimpleNamespace as NS


def apply(report):
    from .evidence_accuracy import image_formats,heading_state
    from .reassess_nine import saved_pages
    pages=saved_pages(report.get('crawl')or{})
    from .structure_data import indexable_pages
    eligible=indexable_pages(NS(pages=pages))
    images=[p for p in eligible if 'images'in p.analysis and 'has_main_region'in p.analysis]
    responses=list(((report.get('crawl')or{}).get('structure')or{}).get('images',{}).values())
    for c in report.get('checks',[]):
        if c['check_id']=='PRF-2':
            from .perf_data import attempts_by_url, request_outcomes, RELIABILITY_DEFINITION
            crawl=report.get('crawl')or{};index=crawl.get('index')or{};perf=crawl.get('perf')or{}
            if all(all(hasattr(p,k)for k in('fetch_class','body_bytes','body_truncated','ttfb_ms','elapsed_ms'))for p in pages):
                from .models import FetchClass
                copied=deepcopy(pages)
                for p in copied:p.fetch_class=FetchClass(p.fetch_class)
                history=attempts_by_url(NS(pages=copied,index=NS(refetches=index.get('refetches')or[]),perf=NS(extra_attempts=perf.get('extra_attempts')or{})))
                c.setdefault('evidence',{}).update(request_outcomes=request_outcomes(history),failure_definition=RELIABILITY_DEFINITION)
        if c['check_id']=='STR-7' and images:
            assessment=image_formats(images,responses)
            c.setdefault('evidence',{})['format_assessment']=assessment
            for f in c.get('findings',[]):
                if 'offered in WebP or AVIF'in f.get('title','') or 'delivery assessed separately'in f.get('title',''):
                    ev=f.setdefault('evidence',{})
                    if 'original_format_scope' not in ev:
                        original=deepcopy(f.get('scope')or{})
                        original['urls']=list(original.get('_all_urls')or original.get('urls')or[])
                        ev['original_format_scope']=original
                    prior=ev['original_format_scope']
                    source_urls=list(prior.get('_all_urls')or prior.get('urls')or[])
                    retained=list(dict.fromkeys(row['page'] for row in assessment['markup_references']))
                    missing=[u for u in source_urls if u not in retained]
                    bound=deepcopy(assessment);bound['source_pages_unassessed']=missing
                    bound['source_scope_count']=prior.get('count');bound['source_membership_complete']=len(source_urls)==prior.get('count',len(source_urls));bound['population']='Retained indexable content page records; missing source page markup is unassessed.'
                    ev['format_assessment']=bound
                    if missing:c.setdefault('evidence',{})['image_format_unassessed_pages']=[{'url':u,'reason':'source page image markup not retained or not eligible for this check'}for u in missing]
                    from .findings import scope_for
                    f['scope']=scope_for(retained)
        if c['check_id']=='STR-2':
            for f in c.get('findings',[]):
                if 'no <h1>'not in f.get('title','') and 'no meaningful <h1>'not in f.get('title',''):continue
                members=set((f.get('scope')or{}).get('_all_urls')or(f.get('scope')or{}).get('urls')or[])
                f.setdefault('evidence',{})['heading_assessments']=[{'url':p.url,**heading_state(p.analysis)}for p in eligible if p.url in members]
    return report
