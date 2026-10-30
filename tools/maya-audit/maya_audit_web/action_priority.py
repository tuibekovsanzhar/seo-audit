"""One advisory action order for summaries, timelines and action plans; does not create engine findings."""
from datetime import datetime, timezone
from .strings import t


def _date(value):
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            pass
    return str(value) if value else t('priority.unknown')


def performance_rows(backlinks=None, speed=None):
    rows = []
    def add(identity, url, device, source, date, metrics, field=False, complete=True, collected=None):
        detail = t('priority.context', url=url or t('priority.unknown'), device=device or t('priority.unknown'),
                   source=source, date=_date(date), collected=_date(collected))
        title = t('priority.field' if field else 'priority.lab', metrics=', '.join(metrics) or t('priority.incomplete'))
        fix = t('priority.field.fix' if field else 'priority.lab.fix') + ' ' + detail
        rows.append({'id': 'diagnostic:' + identity, 'check_id': identity, 'severity': 'S3' if complete else 'S4',
            'severity_label': t('priority.diagnostic'), 'area': 'PRF', 'title': title, 'title_shown': title,
            'fix': fix, 'fix_shown': fix, 'affects': url or t('priority.unknown'),
            'sample_pages': [url] if url else [], 'pages_total': 1 if url and not field else 0,
            'what': title, 'severity_meaning': t('priority.diagnostic'), 'area_label': t('result.family.PRF'),
            'expected': t('priority.field.scope' if field else 'priority.lab.scope'),
            'confidence': 'verified' if field else 'estimated', 'confidence_label': t('priority.field.scope' if field else 'priority.lab.scope'),
            'why': t('priority.field.scope' if field else 'priority.lab.scope'), 'requires_fix': True,
            'source': {'label': source, 'notice': detail}, 'details': [detail],
            'estimates': {'label': t('result.estimates.label'), 'owner':'developer','owner_label':t('owner.developer'),'effort':'M',
                          'effort_label':t('effort.M')}, 'action_kind':'performance_diagnostic'})
    for check in (backlinks or {}).get('checks') or []:
        if check.get('check_id') not in ('DFS-9','DFS-10','DFS-11') or check.get('status') not in ('observed','partial'):
            continue
        evidence = check.get('evidence') or {}
        data = check.get('data') or evidence.get('data') or {}
        bad = data.get('past_good_threshold') or []
        incomplete = bool(data.get('missing_measurements'))
        if not bad and not incomplete:
            continue
        add(check['check_id'],check.get('target'),data.get('device'),'DataForSEO Lighthouse',
            data.get('measurement_at'),bad,complete=bool(bad),
            collected=check.get('data_from') or evidence.get('data_from'))
    if speed and speed.get('status') == 'assessed':
        bad = [m['label'] for m in speed.get('metrics') or [] if m.get('rating') in ('poor','needs_improvement')]
        if bad:
            add('CrUX',speed.get('origin'),speed.get('form_factor'),speed.get('source') or 'Chrome UX Report',
                speed.get('data_until'),bad,field=True,collected=speed.get('fetched_at'))
    return rows


def ordered(rows):
    """Harm tier, evidence quality, importance (a key page or the homepage first, as the engine's `priority_key`),
    observed scope, actionability; input order breaks remaining ties."""
    def key(pair):
        index,row=pair
        quality = 2 if row.get('unverified') else (1 if row.get('confidence') in ('estimated','inferred') else 0)
        tier = {'S1':0,'S2':1,'S3':3,'S4':4,'Info':5}.get(row['severity'],5)
        if row.get('action_kind') and row['severity'] == 'S3':
            tier = 2  # Measured performance diagnostics precede medium editorial/hygiene work, never S1/S2.
        return (tier,quality,row.get('importance',2),
                -int(row.get('pages_total') or 0),{'S':0,'M':1,'L':2}.get(row['estimates']['effort'],3),index)
    return [row for _,row in sorted(enumerate(rows),key=key)]
