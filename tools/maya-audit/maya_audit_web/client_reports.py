"""Evidence-only editorial workspaces. No fetchers, providers, shell or LLM calls.

The saved audit remains authoritative. Editorial review is an attestation, not live verification.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import threading
import tempfile

from maya_audit.client_reporting import from_maya_report as converter
from maya_audit.client_reporting import render_report, validate_cards
from maya_audit.client_reporting.reliability import numbers, reference_text, fully_verified
from . import wording, strings, summary as technical_summary
from .action_priority import performance_rows

# Single process app; shared across requests, not a lock file in the owner's home.
_LOCKS = [threading.RLock() for _ in range(64)]


class Conflict(ValueError):
    pass


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def all_cards(data):
    return data['cards'] + data['appendix_cards']


def references(data):
    out = []
    for url, facts in data.get('page_facts', {}).items():
        for obs in facts.get('observations', []):
            for field in ('title', 'description', 'h1', 'text_sample'):
                value = obs.get(field)
                if value and obs.get('read_at'):
                    ref = {'url': url, 'source': obs['source'], 'field': field, 'read_at': obs['read_at']}
                    text = reference_text([ref], data['page_facts'])
                    if text:
                        out.append({'reference': ref, 'text': text})
    return out


def editorial(card):
    w = card.get('what_to_write') or {}
    return {'title': card.get('title'), 'explanation': card['why'].get('text'), 'steps': card.get('steps', []),
            'proposed_text': w.get('text') or '', 'proposed_code': w.get('code') or '',
            'decision': w.get('decide') or '', 'owner': card.get('owner'), 'effort': card.get('effort'),
            'verify': card.get('verify'), 'references': w.get('derived_from') or []}


def content_hash(work):
    return digest({'summary': work['data']['summary'], 'not_measured': work['data']['not_measured'],
                   'comparison': work['data'].get('changes_since_last'), 'cards': [editorial(c) for c in all_cards(work['data'])]})


def generate(report, audit_id, previous=None, affected=None, performance=None):
    data = converter.convert(deepcopy(report), deepcopy(previous))
    data['meta']['brand'] = data['meta'].get('brand') or data['meta'].get('site') or 'Denetlenen site'
    originals = {f['id']: f for _, f in converter.all_findings(report)}
    for card in all_cards(data):
        f = originals[card['id']]
        previous_language = strings.current_language()
        try:
            strings.set_language('tr')
            row = technical_summary.item(f)
        finally:
            strings.set_language(previous_language)
        card['title'] = row['title_shown']
        card['why']['text'] = row['why']
        # Share normal-report uncertainty and wording, including historical redirect caveats.
        fix = row['fix_shown']
        card['steps'] = ['Kayıtlı bulguyu ve etkilenen adresleri incelemelisiniz.' + (' ' + fix if fix else '')]
        card['verify'] = 'Aynı adresleri ve kontrol koşullarını yeniden değerlendirip sonucu kanıtla kaydetmelisiniz.'
        card['owner'] = {'developer':'Geliştirici','content':'İçerik','seo':'SEO'}[row['estimates']['owner']]
        card['effort'] = {'S':'Küçük','M':'Orta','L':'Büyük'}[row['estimates']['effort']]
        card['action_metadata'] = deepcopy(row.get('judgment',{}).get('action',{}))
        card['what_to_write']['decide'] = 'Karar vermelisiniz: Kanıtı inceleyip uygulanacak değişikliği belirlemelisiniz.'
        if not card['why'].get('text'):
            card['why']['text'] = 'Bu kayıt bir gözlemdir; neden ve iş etkisi inceleme gerektirir.'
        if card['id'] in (affected or {}):
            card['where']['affected_urls'] = affected[card['id']]
        elif (f.get('scope') or {}).get('_all_urls'):
            card['where']['affected_urls'] = list(dict.fromkeys(f['scope']['_all_urls']))
        card['evidence']['snippet'] = '\n'.join((row.get('details') or []) + (row.get('notes_shown') or [])) or 'Ayrıntılı kayıtlı kanıtlar ektedir; yeni canlı doğrulama yapılmadı.'
        source_times=(f.get('evidence')or{}).get('source_collection_times')
        card['evidence']['read_at'] = (source_times[0]if source_times else None)if source_times is not None else f.get('observed_at')
        card['_source_context'] = {'title': row['title_shown'], 'confidence': row['confidence_label'],
                                   'notes': list(dict.fromkeys((row.get('notes_shown') or []) + [wording.note(row['judgment']['interpretation'], 'tr')[0]] + [wording.note(a, 'tr')[0] for a in row['judgment']['alternatives']])), 'scope': row['affects']}
        from maya_audit.client_reporting.advice import procedure
        advice = procedure(f, row)
        card['steps'], card['verify'] = advice['steps'], advice['verify']
        card['what_to_write']['decide'] = advice['decide']
        advice['generated'] = {k: deepcopy(card.get(k)) for k in ('title','steps','verify','why','what_to_write','owner','effort')}
        card['_procedure'] = advice
        card['_editorial_status'] = 'draft'
    data['summary'] = {'one_read': 'Bu taslak yalnızca kayıtlı denetim kanıtlarını kullanır. '
                       'Bulgular ve öneriler müşteriyle paylaşılmadan önce incelenmelidir.', 'bullets': []}
    # Translate saved not-assessed notices; do not remove uncertainty.
    for entry in data['not_measured']:
        if entry['what'] == 'Core Web Vitals and Lighthouse metrics (optional)':
            entry['what'] = 'PageSpeed Insights / CrUX entegrasyonu (ayrı isteğe bağlı panel)'
        else:
            entry['what'] = wording.label(entry['what'], 'tr')[0]
        if entry.get('_needs_tr'):
            entry['why'] = wording.line(entry['why'], 'tr')[0]
            entry['how_to_enable'] = 'Uygun kapsam ve izinlerle ayrıca değerlendirilmelidir.'
        entry.pop('_needs_tr', None)
    for group in (data.get('changes_since_last') or {}).values():
        if isinstance(group, list):
            for row in group:
                if isinstance(row, dict) and row.get('title'):
                    title, translated = wording.title(row.get('check_id') or '', row['title'], 'tr')
                    row['title'] = title
                    if translated:
                        row.pop('_needs_tr', None)
    observation_times = [str(obs['read_at']) for facts in data['page_facts'].values()
                         for obs in facts.get('observations', []) if obs.get('read_at')]
    data['meta']['content_dates'] = {'pages': min(observation_times) if observation_times else 'Mevcut değil'}
    provider_times = []
    cached = False
    for check in (report.get('dataforseo') or {}).get('checks', []):
        ev = check.get('evidence') or {}
        value = check.get('data_from') or ev.get('data_from')
        if isinstance(value, (int, float)):
            try:
                value = datetime.fromtimestamp(value, timezone.utc).isoformat()
            except (ValueError, OSError, OverflowError):
                value = None
        if isinstance(value, str) and value:
            provider_times.append(value)
        cached = cached or bool(ev.get('from_cache'))
    if report.get('dataforseo'):
        data['meta']['content_dates']['search_data'] = ((min(provider_times) if provider_times else 'Mevcut değil') +
            (' (kayıtlı kopya)' if cached else ''))
    old_language = strings.current_language()
    try:
        strings.set_language('tr')
        diagnostics = performance_rows((performance or {}).get('backlinks'), (performance or {}).get('crux'))
    finally:
        strings.set_language(old_language)
    if diagnostics:
        data['summary']['bullets'] = [r['title'] for r in diagnostics[:4]]
    provenance = {'audit_id': audit_id, 'source_digest': digest(report), 'generated_at': now(),
                  'generation': deepcopy(report.get('generation')) or {'engine_version':'historical version not recorded'},
                  'crawl': {k: (report.get('crawl') or {}).get(k) for k in
                            ('origin', 'started_at', 'finished_at', 'config', 'stop_reason', 'stop_detail')},
                  'content_coverage': (report.get('audit_status') or {}).get('content_coverage'),
                  'provider_observations': {p: {k: (report.get(p) or {}).get(k) for k in
                      ('status', 'used', 'from_cache', 'data_from', 'fetched_at', 'observed_at')}
                      for p in ('firecrawl', 'dataforseo', 'crux')}}
    provenance['image_role_gaps'] = deepcopy([row for check in report.get('checks') or []
        for row in (check.get('evidence') or {}).get('unassessed_image_roles') or []])
    # Only assessment controls belong in a client artifact, never credential-bearing configuration.
    config = (report.get('crawl') or {}).get('config') or {}
    provenance['crawl']['config'] = {k: config[k] for k in (
        'max_pages', 'key_pages', 'time_limit_s', 'request_delay_s', 'render_enabled', 'render_budget',
        'render_page_slots', 'redirect_recheck_attempts', 'redirect_recheck_max_hops',
        'sitemap_redirect_check_max_urls', 'llms_max_urls', 'external_links_max', 'check_external_links') if k in config}
    return {'workspace_version': 1, 'audit_id': audit_id, 'source_digest': digest(report), 'revision': 1,
            'data': data, 'provenance': provenance, 'performance': diagnostics, 'review': None,
            'baseline': {'summary': deepcopy(data['summary']), 'cards': {c['id']: editorial(c) for c in all_cards(data)},
                         'not_measured': deepcopy(data['not_measured']), 'comparison': deepcopy(data.get('changes_since_last'))},
            'created_at': now(), 'updated_at': now(),
            'performance_evidence': {'lighthouse': [c for c in (report.get('dataforseo') or {}).get('checks', []) if c.get('check_id') in ('DFS-9', 'DFS-10', 'DFS-11')], 'crux': report.get('crux') or {'status': 'unavailable'}}}


class Workspace:
    def __init__(self, folder: Path, report, audit_id):
        self.path = folder / 'client-report.json'
        self.report, self.audit_id = report, audit_id
        self.lock = _LOCKS[int(sha256(str(self.path).encode()).hexdigest(), 16) % len(_LOCKS)]

    def load(self):
        if not self.path.is_file():
            raise FileNotFoundError('Generate a client draft first / Önce müşteri taslağını oluşturun.')
        if self.path.is_symlink():
            raise Conflict('Client workspace must not be a symbolic link.')
        work = json.loads(self.path.read_text(encoding='utf-8'))
        if work['source_digest'] != digest(self.report):
            raise Conflict('Saved audit evidence changed. Existing edits are preserved; use the matching audit snapshot before continuing.')
        return work

    def write(self, work):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent, prefix='client-report-', suffix='.tmp', delete=False) as stream:
                temp = Path(stream.name)
                json.dump(work, stream, ensure_ascii=False, indent=2)
            temp.replace(self.path)
        finally:
            if temp is not None and temp.exists() and not temp.is_symlink():
                temp.unlink()

    def create(self, **options):
        with self.lock:
            if self.path.exists():
                return self.load()  # Never overwrite editorial work on repeated generation.
            work = generate(self.report, self.audit_id, **options)
            self.write(work)
            return work

    def update(self, revision, change):
        with self.lock:
            work = self.load()
            if work['revision'] != revision:
                raise Conflict('Another editor saved this report. Reload before saving / Rapor değişti; yeniden yükleyin.')
            change(work)
            work['revision'] += 1
            work['updated_at'] = now()
            self.write(work)
            return work


def edit(work, card_id=None, summary=None, fields=None):
    data = work['data']
    if summary is not None:
        data['summary'] = summary
    if card_id is not None:
        card = next((c for c in all_cards(data) if c['id'] == card_id), None)
        if card is None:
            raise ValueError('Unknown finding ID / Bulgu bulunamadı.')
        values = fields
        card.update(title=values['title'], steps=values['steps'], owner=values['owner'], effort=values['effort'], verify=values['verify'])
        card['why']['text'] = values['explanation']
        for group in (data.get('changes_since_last') or {}).values():
            if isinstance(group, list):
                for row in group:
                    if isinstance(row, dict) and row.get('finding_id') == card_id:
                        row['title'] = values['title']
                        row.pop('_needs_tr', None)
        available = references(data)
        try:
            refs = [available[i]['reference'] for i in values['references']]
        except IndexError:
            raise ValueError('Choose a reference from the saved evidence / Kayıtlı kanıttan kaynak seçin.') from None
        card['what_to_write'] = {'text': values['proposed_text'], 'code': values['proposed_code'],
                                 'decide': values['decision'], 'derived_from': refs}
    work['review'] = None
    for c in all_cards(data):
        c['_editorial_status'] = 'draft'
        c['what_to_write'].pop('review', None)


def edit_notes(work, values):
    if len(values['not_measured']) != len(work['data']['not_measured']):
        raise ValueError('Assessment notices cannot be removed / Ölçülmeyen alanlar kaldırılamaz.')
    for row in values['comparison_titles']:
        group = (work['data'].get('changes_since_last') or {}).get(row['group'], [])
        if row['index'] >= len(group):
            raise ValueError('Unknown comparison row / Karşılaştırma satırı bulunamadı.')
        group[row['index']]['title'] = row['title']
        group[row['index']].pop('_needs_tr', None)
    work['data']['not_measured'] = values['not_measured']
    edit(work)  # Same review invalidation as every other editorial save.


def review(work, reviewer, reason):
    record = {'status': 'reviewed', 'reviewer': reviewer.strip(), 'reason': reason.strip(),
              'reviewed_at': now(), 'content_hash': content_hash(work)}
    if not record['reviewer'] or not record['reason']:
        raise ValueError('Reviewer and review reason are required / İnceleyen ve gerekçe gereklidir.')
    work['review'] = record
    for c in all_cards(work['data']):
        c['_editorial_status'] = 'reviewed'
        if c['what_to_write'].get('text') or c['what_to_write'].get('code'):
            c['what_to_write']['review'] = {k: record[k] for k in ('status', 'reviewer', 'reason', 'reviewed_at')}


def validation(work):
    errors, warnings, _ = validate_cards.validate(deepcopy(work['data']))
    record = work.get('review') or {}
    if record.get('content_hash') != content_hash(work):
        errors.append('Editorial review required for this revision / Bu sürüm için içerik incelemesi gerekli.')
    # New numeric claims in prose need saved readable evidence, not just an editorial attestation.
    baseline = work['baseline']
    all_text = '\n'.join(x['text'] for x in references(work['data']))
    candidates = [('summary', work['data']['summary'], baseline['summary']),
                  ('not_measured', {'text': work['data']['not_measured']}, {'text': baseline['not_measured']}),
                  ('comparison', {'text': work['data'].get('changes_since_last')}, {'text': baseline['comparison']})]
    candidates += [(c['id'], editorial(c), baseline['cards'][c['id']]) for c in all_cards(work['data'])]
    for name, changed, original in candidates:
        changed = {k: v for k, v in changed.items() if k != 'references'}
        original = {k: v for k, v in original.items() if k != 'references'}
        if numbers(json.dumps(changed, ensure_ascii=False)) - numbers(json.dumps(original, ensure_ascii=False)) - numbers(all_text):
            errors.append(f'{name}: new numeric claim lacks saved readable evidence / Yeni sayısal iddia kayıtlı okunabilir kanıtla desteklenmiyor.')
    # A review cannot certify a live result or a resolved issue in editable prose.
    import re
    assertion = re.compile(r'\b(verified|fixed|resolved|doğrulandı|giderildi|düzeltildi|kesinlikle|guaranteed)\b', re.I)
    for name, changed, original in candidates:
        added = assertion.findall(json.dumps(changed, ensure_ascii=False))
        prior = assertion.findall(json.dumps(original, ensure_ascii=False))
        if added != prior:
            errors.append(f'{name}: unsupported verification/resolution assertion; use evidence and uncertainty, not a claimed live result.')
    errors.extend(judgment_errors(work))
    return {'valid': not errors, 'errors': errors, 'warnings': warnings,
            'editorial_status': 'reviewed' if record.get('content_hash') == content_hash(work) else 'draft',
            'verified_findings': sum(fully_verified(c) for c in all_cards(work['data'])),
            'notice': 'Structural and lexical validation cannot prove semantic truth. Review is not live verification.'}


def judgment_errors(work):
    """Narrow, source-bound contradiction checks, not a semantic truth classifier.

    Page titles elsewhere are not evidence for a finding's scope. An editorial
    signature cannot remove an inferred diagnosis's uncertainty. Other semantic
    contradictions still require human evidence review.
    """
    import re
    errors = []
    uncertain = re.compile(r'incelenmeli|değerlendirilmeli|olabilir|belirsiz|bilinmiyor|belirlenemedi|tahmin|olası|muhtemel|estimated|likely|'
                           r'kesin değil|doğrulanma|kanıt yetersiz|not assessed|unknown|uncertain|could|may\b', re.I)
    absolute = re.compile(r'hiç\s*kimse\s+tarafından\s+okunamaz|tüm\s+kullanıcılara\s+kapalı|'
                          r'cannot\s+be\s+read\s+by\s+anyone|inaccessible\s+to\s+everyone', re.I)
    scope_claim = re.compile(r'(?<![\w/])([0-9]+)\s+(?:adet\s+)?(?:sayfa(?:yı|da|nın|ları)?|adres(?:i|in|te|leri)?|urls?|pages?)\b', re.I)
    for c in all_cards(work['data']):
        original = work['baseline']['cards'][c['id']]
        current = editorial(c)
        for field in ('title', 'explanation'):
            text = current.get(field) or ''
            if absolute.search(text):
                errors.append(f'{c["id"]}.{field}: unsupported universal access conclusion / Evrensel erişim iddiası desteklenmiyor; kaydedilen istemci, zaman ve kapsamı belirtin.')
            if text == original.get(field):
                continue
            if ((c.get('maya') or {}).get('confidence') in ('inferred', 'estimated', 'not_assessed', 'unknown') or (c.get('maya') or {}).get('evidence_limits') or (c.get('judgment') or {}).get('status') in ('diagnostic_concern','contradictory_evidence','not_assessed','owner_context_required')) and not uncertain.search(text):
                errors.append(f'{c["id"]}.{field}: preserve source uncertainty / Kaynak belirsizliğini koruyun; içerik incelemesi kanıtı kesinleştirmez.')
        # Check additions across every editorial field, not only title/explanation.
        # Only counts explicitly phrased as page/address quantities are bound here;
        # dates, prices, occurrences and template groups have different units.
        expected = (c.get('where') or {}).get('count')
        for field, value in current.items():
            if field == 'references' or value == original.get(field):
                continue
            text = json.dumps(value, ensure_ascii=False)
            if field not in ('title', 'explanation') and absolute.search(text):
                errors.append(f'{c["id"]}.{field}: unsupported universal access conclusion / Kayıtlı gözlemin kapsamını aşan erişim iddiası.')
            judgment = c.get('judgment') or {}
            consequential = re.search(r'(?:(?:sitemap|bağlantı|adres|url|sayfa).{0,35}(?:çıkar|kaldır|sil)|noindex|birleştir|consolidat|(?:remove|delete).{0,35}(?:url|link|page|sitemap)|merge.{0,35}page)', text, re.I)
            conditional = re.search(r'önce|ancak|karar|doğrula|incelen|gerekiyorsa|eğer|owner|before|only if|do not|unless|review|corroborat|confirm|mamalı|memeli|değil', text, re.I)
            if consequential and judgment.get('qualified') and not conditional:
                errors.append(f'{c["id"]}.{field}: consequential action requires corroboration / owner decision; review cannot establish the missing evidence.')
            prior = set(scope_claim.findall(json.dumps(original.get(field), ensure_ascii=False)))
            for count in set(scope_claim.findall(text)) - prior:
                if re.search(r'örnek|sample', text, re.I) and isinstance(expected, int) and 0 < int(count) <= expected:
                    continue
                if expected is None or int(count) != expected:
                    errors.append(f'{c["id"]}.{field}: affected-page count {count} contradicts saved scope {expected} / Etkilenen sayfa sayısını kayıtlı kapsamla eşleştirin; örneklem veya işlem adımını sayfa sayısı olarak sunmayın.')
    text = json.dumps(work['data']['summary'], ensure_ascii=False)
    healthy = re.search(r'hiçbir\s+sorun\s+yok|site\s+sorunsuz|no\s+issues\s+found', text, re.I)
    if healthy and (any(c['maya']['severity_report'] != 'Info' for c in all_cards(work['data']))
                    or work['data']['coverage'].get('score_status') != 'assessed_sample'):
        errors.append('summary: healthy conclusion contradicts findings or incomplete assessment / Sorunsuz iddiası bulgular veya eksik değerlendirmeyle çelişiyor.')
    return errors


def public(work):
    return {k: v for k, v in work.items() if k != 'baseline'} | {'validation': validation(work), 'references': references(work['data'])}


def html(work, draft=True, *, full=False, origin=None):
    result = validation(work)
    if not draft and not result['valid']:
        raise ValueError('Final report rejected / Son rapor reddedildi:\n' + '\n'.join(result['errors']))
    render_data = deepcopy(work['data'])
    for card in all_cards(render_data):
        if card.get('_source_context'):
            # Older sidecars can contain English notes. Do not mark an already Turkish
            # sentence as English merely because it is not an English lookup key.
            translated=[]
            for note in card['_source_context'].get('notes') or []:
                shown,known=wording.note(note,'tr')
                translated.append(shown if known else note)
            card['_source_context']['notes']=translated
        if not card.get('_source_context'):
            # Older workspaces stay readable without rewriting their saved sidecar.
            original = work['baseline']['cards'][card['id']]
            card['_source_context'] = {'title': original.get('title'),
                'confidence': (card.get('maya') or {}).get('confidence'),
                'scope': (card.get('where') or {}).get('count'),
                'notes': (card.get('_draft') or {}).get('notes_en') or []}
    text = render_report.build(render_data, draft=draft, group_large=not full)
    if not full:
        return compact_evidence(text, work, result, origin=origin)
    e = lambda x: escape(str(x), quote=True)
    important = [c for c in work['data']['appendix_cards'] if c['severity'] in ('Kritik', 'Yüksek')]
    notice = ('<aside class="coverage"><b>Ana bölüm dışında önemli bulgular: ' + str(len(important)) + '</b><ul>' +
              ''.join('<li>' + e(c['title']) + '</li>' for c in important) + '</ul> Tüm ayrıntılar ektedir.</aside>') if important else ''
    def table(rows, identity=None):
        header = '<thead><tr><th colspan="2">' + e(identity) + '</th></tr></thead>' if identity else ''
        return '<table>'+header+'<tbody>' + ''.join('<tr><th>' + e(k) + '</th><td>' + e(v if v is not None else 'Mevcut değil') + '</td></tr>' for k, v in rows) + '</tbody></table>'
    prov = work['provenance']
    crawl = prov['crawl']
    evidence = '<section><h2>Kanıt kapsamı ve inceleme durumu</h2><p>' + e(result['editorial_status']) + \
        '; doğrulanmış bulgu: ' + str(result['verified_findings']) + '. İçerik incelemesi canlı doğrulama değildir.</p>'
    evidence += table([('Denetim', prov['audit_id']), ('Kaynak özeti (source_digest)', prov['source_digest']),
        ('Yerel tarama başlangıcı', crawl.get('started_at')), ('Yerel tarama bitişi', crawl.get('finished_at')),
        ('Tüm işin bitişi (kayıtlıysa)', (prov.get('generation') or {}).get('whole_job_finished_at')),
        ('Analiz işleme zamanı', (prov.get('generation') or {}).get('processed_at')),
        ('Bu dışa aktarımın üretim zamanı', now()),
        ('İçerik tarihleri', json.dumps(work['data']['meta'].get('content_dates'), ensure_ascii=False)),
        ('Ölçülen kapsam', work['data']['coverage'].get('line')), ('Puan kapsamı', work['data']['coverage'].get('score_reason'))])
    evidence += '<h3>Tarama sınırları ve örnekleme</h3>' + table(list(crawl.get('config', {}).items()))
    evidence += '<h3>İşlem sürümü ve ayrı aşama kapsamları</h3><p>Yerel tarama bitişi tüm işin bitişi değildir. Sayfalar, bağlantı/sitemap yoklamaları ve okuyucu denemeleri ayrı kapsamlardır.</p>'
    from maya_audit.report_layout import evidence_parts
    for part in evidence_parts(prov.get('generation') or {'engine_version':'not recorded'}):
        evidence += '<pre class="evidence-part">' + e(part) + '</pre>'
    evidence += '<p>' + e(json.dumps(prov.get('content_coverage'), ensure_ascii=False)) + '</p>'
    evidence += '<h3>Sağlayıcı durumu ve kayıt tarihleri</h3>' + table([(k, json.dumps(v, ensure_ascii=False)) for k, v in prov['provider_observations'].items()])
    if prov.get('image_role_gaps'):
        evidence += '<h3>Değerlendirilemeyen görsel rolleri — kusur yokluğu anlamına gelmez</h3>'
        for gap in prov['image_role_gaps']:
            evidence += table([('Sayfa', gap.get('url')), ('Görsel / öğe', str(gap.get('src')) + ' / ' + str(gap.get('element_id'))),
                ('Gözlem kaynağı / zamanı', str(gap.get('source')) + ' / ' + str(gap.get('observed_at'))),
                ('Eksik değerlendirme', 'Görüntü, CSS, işlev ve eşdeğer metin birlikte incelenmelidir.'),
                ('Kayıtlı bağlam', json.dumps(gap.get('context'), ensure_ascii=False))], identity=str(gap.get('element_id') or gap.get('src')))
    evidence += '<h3>Performans kanıtları</h3>'
    if not work['performance']:
        evidence += '<p>İyileştirme gerektiren kayıtlı performans ölçümü mevcut değil. Eksik veri sağlıklı sonuç değildir.</p>'
    for row in work['performance']:
        evidence += '<h4>' + e(row['title']) + '</h4><p>' + e(row['why']) + '</p><p>' + e(row['fix']) + '</p>'
    evidence += '<pre>' + e(json.dumps(work['performance_evidence'], ensure_ascii=False, indent=2)) + '</pre>'
    evidence += '<h3>Okunabilir kanıt kaynakları (kayıtlı gözlemler)</h3>'
    for url, facts in work['data']['page_facts'].items():
        for obs in facts.get('observations', []):
            evidence += table([('Kaynak', obs.get('source')), ('Gözlem zamanı', obs.get('read_at')),
                ('Önbellek (from_cache)', obs.get('from_cache')), ('İçerik kaydı', obs.get('provenance')),
                ('Başlık', obs.get('title')), ('Açıklama', obs.get('description')), ('Ana başlık', obs.get('h1')),
                ('Okunabilir metin', obs.get('text_sample'))], identity=url)
    evidence += '<h3>Tüm etkilenen adresler ve kayıtlı kaynaklar</h3>'
    for c in all_cards(work['data']):
        from maya_audit.report_layout import evidence_parts
        raw = deepcopy(c['_draft'].get('evidence_raw'))
        if isinstance(raw, dict) and raw.get('judgment'):
            # Qualified source context is already rendered above, not raw website evidence.
            raw.pop('judgment')
            raw['qualified_decision_reference'] = 'Companion JSON: evidence.judgment'
        payload = {'scope': c['where'], 'counting': c.get('counting'), 'source': c['maya'].get('source'),
                   'confidence': c['maya'].get('confidence'), 'observation_time': c['evidence'].get('read_at'),
                   'verification': c['evidence'].get('verification'), 'evidence': raw}
        parts = evidence_parts(payload)
        for index, part in enumerate(parts, 1):
            evidence += '<h4 class="evidence-identity">' + e(c['id']) + ' · ' + e(c['title']) + ' · ' + str(index) + '/' + str(len(parts)) + '</h4><pre class="evidence-part">' + e(part) + '</pre>'
    evidence += '</section>'
    # Static HTML only. All inserted data is escaped. Existing renderer also escapes editorial values.
    quality = '<aside class="coverage">İçerik incelemesi: ' + ('incelendi' if result['editorial_status'] == 'reviewed' else 'taslak') + '; gerçek canlı doğrulama: ' + str(result['verified_findings']) + ' bulgu. İçerik incelemesi canlı doğrulama değildir.</aside>'
    return text.replace('<div class="kpis">', quality + notice + '<div class="kpis">', 1).replace('</div></body>', evidence + '</div></body>')


def plain(value):
    """A recorded value as words for a client page: "pages 2026-10-21; search_data …", never a JSON or Python dump."""
    if isinstance(value, dict):
        return '; '.join(f'{k}: {plain(v)}' for k, v in value.items() if v not in (None, '', [], {})) or 'Mevcut değil'
    if isinstance(value, (list, tuple)):
        return ', '.join(plain(v) for v in value) or 'Mevcut değil'
    return 'Mevcut değil' if value is None else str(value)


def compact_evidence(text, work, result, *, origin=None):
    """Readable delivery view; full immutable source detail lives in companion exports.

    The procedure of each finding is said in full in the main section; the appendix is one row per finding (CR-12).
    Exhaustive raw records and page extracts move to an explicitly labelled companion, named by its file name: a
    link into the owner's local app (127.0.0.1) does not open on a client's computer (D-08). `origin` is kept for
    callers and no longer used.
    """
    e = lambda value: escape(str(value if value is not None else 'Mevcut değil'), quote=True)
    prov = work['provenance']; crawl = prov['crawl']; generation = prov.get('generation') or {}
    rows = [('Denetim / Analysis', prov['audit_id']), ('Kaynak özeti / source_digest', prov['source_digest']),
            ('Yerel tarama başlangıcı', crawl.get('started_at')), ('Yerel tarama bitişi', crawl.get('finished_at')),
            ('Tüm işin bitişi (kayıtlıysa)', generation.get('whole_job_finished_at')),
            ('Analiz işleme zamanı', generation.get('processed_at')), ('Dışa aktarım zamanı', now()),
            ('İçerik gözlem tarihleri', plain(work['data']['meta'].get('content_dates'))),
            ('Tarama sınırları', plain(crawl.get('config'))),
            ('İşlem sürümü / kaynak', generation.get('source_commit') or generation.get('engine_version'))]
    appendix = '<section><h2>Kanıt kapsamı / Evidence scope</h2><p>İçerik incelemesi: ' + e(result['editorial_status']) + '; canlı doğrulanmış bulgu: ' + str(result['verified_findings']) + '. İçerik incelemesi canlı doğrulama değildir.</p>'
    appendix += '<table><thead><tr><th>Alan</th><th>Kayıtlı değer</th></tr></thead><tbody>' + ''.join('<tr><td>' + e(k) + '</td><td>' + e(v) + '</td></tr>' for k,v in rows) + '</tbody></table>'
    gaps = prov.get('image_role_gaps') or []
    appendix += '<h3>Değerlendirilemeyen görsel rolleri</h3><p>Değerlendirilemeyen görsel rolü kayıtları: ' + str(len(gaps)) + '. Bunlar başarılı değerlendirme veya doğrulanmış kusur olarak sayılmaz; görsel, CSS, işlev ve eşdeğer metin birlikte incelenmelidir. Tam bağlam JSON ekindedir.</p>'
    important = [c for c in work['data']['appendix_cards'] if c['severity'] in ('Kritik', 'Yüksek')]
    if important:
        appendix += '<p><b>Ana bölüm dışında önemli bulgular: ' + str(len(important)) + '</b> — tüm kimlikler ve ayrıntılar yukarıdaki ekte korunmuştur.</p>'
    appendix += '<h3>Sağlayıcı gözlemleri / Provider observations</h3><table><thead><tr><th>Kaynak</th><th>Durum / tarih / from_cache</th></tr></thead><tbody>' + ''.join('<tr><td>' + e(k) + '</td><td>' + e(plain(v)) + '</td></tr>' for k,v in prov.get('provider_observations',{}).items()) + '</tbody></table>'
    appendix += '<h3>Performans / Performance</h3>'
    if not work.get('performance'):
        appendix += '<p>Kayıtlı performans önerisi mevcut değil; eksik ölçüm sağlıklı sonuç değildir.</p>'
    for row in work.get('performance') or []:
        appendix += '<h4>' + e(row['title']) + '</h4><p>' + e(row['why']) + '</p><p>' + e(row['fix']) + '</p>'
    for check in (work.get('performance_evidence') or {}).get('lighthouse') or []:
        data = check.get('data') or (check.get('evidence') or {}).get('data') or {}
        metrics = data.get('metrics') or {}
        if metrics:
            appendix += '<p><b>Lighthouse — tek laboratuvar koşusu, gerçek kullanıcı CWV değil</b> · ' + e(check.get('target')) + ' · ' + e(data.get('device')) + ' · ' + e(data.get('measurement_at')) + '</p>'
            appendix += '<table><thead><tr><th>Ölçüm</th><th>Kayıtlı değer</th></tr></thead><tbody>' + ''.join('<tr><td>' + e(k) + '</td><td>' + e(v) + '</td></tr>' for k,v in metrics.items()) + '</tbody></table>'
    appendix += '<h3>Tam kanıt ekleri / Full evidence companions</h3><p>Adres listeleri ve kısa kanıtlar örnektir; tam kayıtlar bu raporla birlikte iletilen dosyalardadır.</p>'
    audit = work['audit_id']
    appendix += ('<ul><li>Tam müşteri kanıtı JSON / Complete client evidence JSON: ' + e(f'maya-client-{audit}-evidence.json') + '</li>'
                 '<li>Tam teknik müşteri eki HTML / Exhaustive evidence: ' + e(f'maya-client-{audit}-draft-full-evidence.html') + '</li>'
                 '<li>Kaynak teknik rapor JSON / Source technical report: Maya Audit “JSON” indirmesi</li></ul></section>')
    return text.replace('</head>', '<meta name="maya-client-compact" content="50-page-maximum"><style>@media print{.card{break-inside:auto;page-break-inside:auto}.card .head{break-before:auto}.card>.coverage{break-inside:avoid}.card .small{overflow-wrap:anywhere}}</style></head>', 1).replace('</div></body>', appendix + '</div></body>')
