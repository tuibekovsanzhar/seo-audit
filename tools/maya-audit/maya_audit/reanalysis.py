"""Refresh derived metrics of an explicitly copied analysis, without rejudging evidence."""
from copy import deepcopy
from .report import read_counts, problem_summary, coverage_note, also_fetched, read_status_summary


def refresh_metrics(report, affected=None):
    report = deepcopy(report)
    counts = read_counts(report.get('crawl') or {}, report.get('firecrawl'))
    coverage = (report.get('audit_status') or {}).get('content_coverage')
    if coverage is not None:
        coverage.update(pages_read=counts['pages'], readable_unique_urls=counts['pages'],
                        read_by=counts['read_by'], other_addresses=counts['other_addresses'])
        if not counts['pages']:
            coverage['level'] = 'none'
        also = also_fetched(counts['other_addresses'])
        coverage['note'] = coverage_note(coverage['level'], counts['pages']) + (' '+also if also else '')
    if coverage is not None:
        from .coverage import restated
        for check in report.get('checks', []):
            scope = check.get('coverage') or {}
            if scope.get('not_assessed'):
                scope['not_assessed'] = restated(scope['not_assessed'], counts['pages'], coverage.get('known_urls_not_read', 0))
        status = report['audit_status']
        if status.get('direct_access') and status.get('vendor_crawler_evidence'):
            status['summary'] = read_status_summary(status, counts)
    findings = [f for c in report.get('checks', []) for f in c.get('findings', [])]
    old = report.get('problem_summary') or {}
    report['problem_summary'] = problem_summary(findings, affected, pages_checked=counts['pages'],
        checks=report.get('checks'), single_page=(old['single_page'].get('url') if isinstance(old.get('single_page'), dict) else old.get('single_page')), start_address=old.get('start_address'))
    return report


def markdown(report, affected=None):
    """Technical Markdown for a copied canonical analysis, not stale source report.md.

    Source measurements and original times are never reconstructed. The full structured
    evidence remains in the companion JSON rather than an invented live verification.
    """
    meta=(report.get('generation') or {}).get('analysis') or {}
    lines=['# '+str(meta.get('label') or 'Saved-evidence reassessment'),'',
           'Analysis ID: '+str(meta.get('id') or 'not recorded'),
           'Analysis version: '+str(meta.get('analysis_version') or 'not recorded'),
           'Original source audit: '+str(meta.get('source_audit_id') or 'not recorded'),
           'Original native collection: '+str((report.get('crawl') or {}).get('started_at'))+' → '+str((report.get('crawl') or {}).get('finished_at')),
           'Processing time: '+str(meta.get('processed_at') or 'not recorded'),
           'This is offline reprocessing, not a fresh website check. Complete evidence: companion JSON.', '']
    by_id={f['id']:f for c in report.get('checks',[]) for f in c.get('findings',[])}
    order=list(dict.fromkeys(list(report.get('findings_in_priority_order') or [])+list(by_id)))
    for identity in order:
        if identity not in by_id:continue
        f=by_id[identity];j=(f.get('evidence') or {}).get('judgment') or {};a=j.get('action') or {}
        lines+=['## '+identity+' — '+f['title'],
                f"Severity: {f['severity']} · Confidence: {f['confidence']} · Decision: {j.get('status','not assessed')}",
                'Observation: '+str(j.get('observation') or f['title']),
                'Interpretation: '+str(j.get('interpretation') or 'not assessed'),
                'Action: '+str(a.get('text') or f.get('how_to_fix') or 'not assessed'),
                'Owner / effort (estimates): '+str(a.get('owner'))+' / '+str(a.get('effort')),
                'Verification: '+str(a.get('verification') or 'not assessed')]
        lines+=['Alternative: '+str(v) for v in j.get('alternatives',[])]
        lines+=['- '+str(u) for u in (affected or {}).get(identity,(f.get('scope')or{}).get('urls')or[])]
        lines.append('')
    lines+=['## Unassessed scope','']
    for c in report.get('checks',[]):
        for gap in (c.get('coverage')or{}).get('not_assessed')or[]:
            lines.append(c['check_id']+' — '+gap['part']+': '+gap['reason'])
    return '\n'.join(lines)+'\n'
