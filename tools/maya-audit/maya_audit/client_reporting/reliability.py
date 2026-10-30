"""Conservative client-report contracts. No network, storage access, or semantic truth claims."""
from datetime import datetime, timezone
import re


def timestamp(value):
    if not isinstance(value, str) or 'T' not in value:
        return False
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt.tzinfo is not None and dt <= datetime.now(timezone.utc)
    except ValueError:
        return False


def assessment(report):
    content = (report.get('audit_status') or {}).get('content_coverage') or {}
    checks = report.get('checks') or []
    pages = content.get('pages_read')
    ran = [c for c in checks if c.get('status') in ('pass', 'findings', 'observed', 'needs_review', 'partial')]
    level = content.get('level')
    result = {'pages_read': pages, 'assessment_level': level, 'assessed_checks': len(ran),
              'checks_total': len(checks), 'check_denominators': {}, 'score_status': 'unavailable'}
    for c in ran:
        # Only use a documented per-check assessment count, not all known site URLs.
        ev = c.get('evidence') or {}
        n = ev.get('listed_urls_assessed') if c.get('check_id') == 'IDX-5' else pages
        if isinstance(n, int) and not isinstance(n, bool) and n > 0:
            result['check_denominators'][c.get('check_id')] = n
    if not isinstance(pages, int) or isinstance(pages, bool) or pages <= 0 or not ran or level not in ('partial', 'complete_sample'):
        result['score_reason'] = 'Puan hesaplanamadı: sayfa veya değerlendirme kanıtı yok.'
    else:
        partial = level != 'complete_sample' or len(ran) != len(checks) or any(
            c.get('status') in ('partial', 'needs_review') or (c.get('coverage') or {}).get('not_assessed') for c in checks)
        partial = partial or any((c.get('evidence') or {}).get('unassessed_image_roles') for c in checks)
        result['score_status'] = 'partial' if partial else 'assessed_sample'
        result['score_reason'] = f"{'Kısmi' if partial else 'Örneklem'} puan (taslak): {pages} okunan sayfa, {len(ran)}/{len(checks)} kontrol; site geneli puanı değildir."
    return result


def score_label(value, cov):
    return 'Hesaplanamadı' if value is None else f"{value}/100 ({'kısmi ' if cov.get('score_status') == 'partial' else ''}taslak)"


def verification(card):
    """Return valid records only; a legacy date never verifies a claim or a whole scope."""
    records = (card.get('evidence') or {}).get('verification') or []
    if not isinstance(records, list):
        return []
    code = (card.get('maya') or {}).get('check_id')
    affected = set((card.get('where') or {}).get('affected_urls') or (card.get('where') or {}).get('examples') or [])
    return [r for r in records if isinstance(r, dict) and r.get('check_id') == code and code
            and r.get('url') in affected and timestamp(r.get('checked_at'))
            and r.get('method') in ('live_http', 'live_browser') and r.get('conclusion') == 'confirmed'
            and isinstance(r.get('evidence'), str) and r['evidence'].strip() and r.get('what_checked')]


def fully_verified(card):
    w = card.get('where') or {}
    urls = set(w.get('affected_urls') or w.get('examples') or [])
    count = w.get('count')
    return bool(urls) and isinstance(count, int) and count == len(urls) and urls <= {r['url'] for r in verification(card)}


def page_facts(report):
    """Saved reports omit _visible_text. Never recover it from hashes or provider metadata."""
    out = {}
    for p in (report.get('crawl') or {}).get('pages') or []:
        url, a = p.get('url'), p.get('analysis') or {}
        if not url or not a or p.get('content_checks_eligible') is not True:
            continue
        source = 'provider' if p.get('view') == 'provider' else 'native'
        obs = {'source': source, 'url': url, 'read_at': p.get('requested_at'),
               'title': a.get('title'),
               'h1': next((h.get('text') for h in a.get('headings') or [] if h.get('level') == 1), None),
               'description': next((m.get('content') for m in a.get('meta') or [] if (m.get('name') or '').lower() == 'description'), None),
               'text_sample': None, 'status': p.get('status'),
               'provenance': 'crawl.pages[].analysis', 'readable_text_available': False}
        # Public analysis does not promise a readable body field. Titles/headings/meta are actual strings.
        out[url] = {**obs, 'observations': [obs.copy()]}
    fc = report.get('firecrawl') or {}
    if fc.get('used'):
        for p in fc.get('pages') or []:
            if p.get('outcome') != 'read' or not p.get('url'):
                continue
            url = p['url']
            obs = {'source': 'firecrawl', 'url': p.get('final_url') or url, 'requested_url': url,
                   'read_at': p.get('observed_at'), 'status': p.get('status'), 'from_cache': p.get('from_cache'),
                   'title': None, 'h1': None, 'description': None, 'text_sample': None,
                   'readable_text_available': False, 'provenance': 'firecrawl.pages[] (metadata only)'}
            if url not in out:
                out[url] = {**obs, 'observations': []}
            out[url]['observations'].append(obs)
    return out


def findings(report):
    for section in ('checks', 'answer_engine_panel'):
        for c in report.get(section) or []:
            for f in c.get('findings') or []:
                yield {**f, 'check_id': f.get('check_id') or c.get('check_id')}


def finding_key(f):
    scope = f.get('scope') or {}
    # Generated engine IDs include title. A changed ID has no assumed semantic match.
    return (f.get('check_id'), f.get('id'), scope.get('kind'), tuple(sorted(scope.get('urls') or [])), scope.get('count'))


def resolution_evidence(cur, prev, f):
    """Stricter than UI 'no longer reported': complete comparable question and all named pages."""
    code = f.get('check_id')
    chk = next((c for c in cur.get('checks', []) + cur.get('answer_engine_panel', []) if c.get('check_id') == code), {})
    oldchk = next((c for c in prev.get('checks', []) + prev.get('answer_engine_panel', []) if c.get('check_id') == code), {})
    if chk.get('status') != 'pass' or (chk.get('coverage') or {}).get('not_assessed'):
        return None, 'Yeni kontrolde karşılaştırılabilir tam geçer kanıtı yok.'
    a, b = cur.get('crawl') or {}, prev.get('crawl') or {}
    if not a.get('origin') or not cur.get('scope') or not a.get('config') or a.get('origin') != b.get('origin') or cur.get('scope') != prev.get('scope') or a.get('config') != b.get('config'):
        return None, 'Hedef veya değerlendirme koşulları değişmiş ya da bilinmiyor.'
    source = (f.get('evidence') or {}).get('source') or {}
    if source != ((chk.get('evidence') or {}).get('source') or {}) or source != ((oldchk.get('evidence') or {}).get('source') or {}):
        return None, 'Kanıt kaynağı değişmiş.'
    for name in ('firecrawl', 'dataforseo', 'crux'):
        if prev.get(name) and not cur.get(name):
            return None, 'Önceki sağlayıcı verisi yeni raporda yok.'
    scope = f.get('scope') or {}
    urls = set(scope.get('urls') or [])
    if not urls or scope.get('count') != len(urls) or scope.get('kind') == 'sitewide':
        return None, 'Tam etkilenen URL kapsamı karşılaştırılamıyor.'
    content = (cur.get('audit_status') or {}).get('content_coverage') or {}
    if content.get('level') != 'complete_sample':
        return None, 'Yeni içerik kapsamı eksik.'
    read = {p.get('url'): p for p in a.get('pages', []) if p.get('analysis') and p.get('content_checks_eligible') is True and timestamp(p.get('requested_at'))}
    if not timestamp(a.get('started_at')) or not timestamp(b.get('started_at')) or datetime.fromisoformat(a['started_at'].replace('Z','+00:00')) <= datetime.fromisoformat(b['started_at'].replace('Z','+00:00')):
        return None, 'Yeni denetimin zamanı daha yeni değil veya bilinmiyor.'
    previous_reads = {p.get('url'): p.get('requested_at') for p in b.get('pages', [])}
    if any(not timestamp(previous_reads.get(u)) or u not in read or datetime.fromisoformat(read[u]['requested_at'].replace('Z','+00:00')) <= datetime.fromisoformat(previous_reads[u].replace('Z','+00:00')) for u in urls):
        return None, 'Sayfa kanıtı önceki gözlemden yeni değil veya bilinmiyor.'
    if not urls <= read.keys():
        return None, 'Etkilenen sayfaların tamamı yeniden okunmadı.'
    if source.get('reader'):
        # Metadata-only provider rows do not establish which content question was resolved.
        return None, 'Sağlayıcının çözüldüğünü gösteren sayfa kanıtı yok.'
    return {'check_id': code, 'status': 'pass', 'urls': sorted(urls),
            'observed_at': {u: read[u]['requested_at'] for u in sorted(urls)},
            'assessment': chk.get('evidence') or {}, 'conditions': {'origin': a.get('origin'), 'config': a.get('config'), 'scope': cur.get('scope')}}, None


def compare_reports(cur, prev):
    now = list(findings(cur)); before = list(findings(prev))
    out = {'previous_date': ((prev.get('crawl') or {}).get('started_at') or '')[:10] or None,
           'fixed': [], 'new': [], 'still_open': [], 'unknown': []}
    def row(f, **extra):
        return {'title': f.get('title'), 'count': (f.get('scope') or {}).get('count'),
                'check_id': f.get('check_id'), 'finding_id': f.get('id'), 'scope': f.get('scope'), '_needs_tr': True, **extra}
    used = set()
    for old in before:
        exact = next((i for i, f in enumerate(now) if f.get('id') and finding_key(f) == finding_key(old)), None)
        if exact is not None:
            used.add(exact);out['still_open'].append(row(now[exact]));continue
        # Another finding for the same check is ambiguous, even when only its wording differs.
        if any(f.get('check_id') == old.get('check_id') for f in now):
            out['unknown'].append(row(old, reason='Bulgu kimliği veya kapsamı değişmiş.'));continue
        evidence, reason = resolution_evidence(cur, prev, old)
        out['fixed' if evidence else 'unknown'].append(row(old, resolution=evidence) if evidence else row(old, reason=reason))
    for i, f in enumerate(now):
        if i not in used:
            out['unknown' if any(x.get('check_id') == f.get('check_id') for x in before) else 'new'].append(row(f, reason='İlk gözlem; oluşma zamanı bilinmiyor.'))
    return out


def strings(value, path=''):
    """Every public leaf, including deeply nested recommendation text/code; private source data excluded."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            if not k.startswith('_') and k not in ('page_facts', 'maya', 'derived_from', 'review', 'verification', 'resolution', 'judgment', 'action_metadata'):
                yield from strings(v, f'{path}.{k}' if path else k)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from strings(v, f'{path}[{i}]')


def numbers(text):
    return {re.sub(r'\s+', '', x) for x in re.findall(r'(?<!\w)[+-]?(?:%\s*)?\d+(?:[.,:/-]\d+)*(?:\s*%)?', text or '')}


def reference_text(refs, facts, required_source=None):
    texts = []
    if not isinstance(refs, list) or not refs:
        return None
    for ref in refs:
        if not isinstance(ref, dict):
            return None
        url, field, source = ref.get('url'), ref.get('field'), ref.get('source')
        if required_source and source != required_source:
            return None
        obs = next((o for o in (facts.get(url) or {}).get('observations', [])
                    if o.get('source') == source and o.get('url') == url and o.get('read_at') == ref.get('read_at')
                    and timestamp(o.get('read_at'))), None)
        if not obs or not obs.get('provenance') or field not in ('title','h1','description','text_sample') or not isinstance(obs.get(field), str) or not obs[field].strip():
            return None
        texts.append(obs[field])
    return '\n'.join(texts)


def safety_errors(d, norm_words):
    errors = []
    if d.get('contract_version') != 2:
        errors.append('contract_version: final çıktı için sürüm 2 gerekli; eski girdiyi yeniden dönüştürün veya --draft kullanın')
    meta = d.get('meta') or {}
    if not meta.get('brand') or not meta.get('site'):
        errors.append('meta: brand ve site gerekli')
    try:
        datetime.strptime(meta.get('audit_date') or '', '%Y-%m-%d')
    except (ValueError, TypeError):
        errors.append('meta.audit_date: geçerli YYYY-MM-DD tarihi gerekli')
    for i, k in enumerate(d.get('kpis') or []):
        if not isinstance(k, dict) or not k.get('label') or not isinstance(k.get('value'), str):
            errors.append(f'kpis[{i}]: label ve metin value gerekli')
    cov = d.get('coverage') or {}
    sc = d.get('score') or {}
    status = cov.get('score_status')
    if status not in ('unavailable','partial','assessed_sample'):
        errors.append('coverage.score_status: değerlendirme kapsamı eksik')
    if sc.get('status') != status or sc.get('scope') != cov.get('score_reason') or sc.get('draft') is not True:
        errors.append('score: taslak etiketi ve kapsam coverage ile eşleşmeli')
    if status != 'unavailable' and (cov.get('assessment_level') not in ('partial', 'complete_sample') or
            not isinstance(cov.get('checks_total'), int) or not isinstance(cov.get('assessed_checks'), int) or
            not 0 < cov['assessed_checks'] <= cov['checks_total']):
        errors.append('coverage: değerlendirme düzeyi ve kontrol sayıları tutarsız')
    if status == 'assessed_sample' and (cov.get('assessment_level') != 'complete_sample' or cov.get('assessed_checks') != cov.get('checks_total')):
        errors.append('coverage: eksik değerlendirme kısmi olarak etiketlenmeli')
    value = sc.get('value')
    if status == 'unavailable' and value is not None:
        errors.append('score.value: ölçülmeyen değerlendirme sayısal puan olamaz')
    if status != 'unavailable' and (not isinstance(cov.get('pages_read'),int) or cov['pages_read'] <= 0 or not cov.get('assessed_checks')):
        errors.append('score: değerlendirme kanıtı eksik')
    if value is None and status != 'unavailable':
        errors.append('score.value: sayısal değerlendirme eksik; unavailable kullanın')
    if value is not None and (not isinstance(value,(float,int)) or isinstance(value,bool) or not 0 <= value <= 100):
        errors.append('score.value: 0–100 veya null olmalı')
    # The draft score is shown on the cover with its draft label, never as a KPI box (H25): an uncalibrated number is
    # not the first figure a client reads.
    if any(k.get('value') == score_label(value, cov) or 'puan' in str(k.get('label') or '').lower() for k in d.get('kpis', [])
           if isinstance(k, dict)):
        errors.append('kpis: taslak puan KPI kutusunda gösterilmez; kapakta taslak etiketiyle görünür')
    from .from_maya_report import score, load_json, REFS
    from copy import deepcopy
    expected, _ = score(deepcopy(d.get('cards',[]) + d.get('appendix_cards',[])), cov, load_json(REFS / 'onem_kurallari.json')['score'])
    if value != expected:
        errors.append('score.value: kanıta göre yeniden hesaplanan puanla eşleşmiyor')
    ids = [c.get('id') for c in d.get('cards',[]) + d.get('appendix_cards',[])]
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        errors.append('cards: benzersiz dolu id gerekli')
    for group in ('cards','appendix_cards'):
        for c in d.get(group,[]):
            p = f"{group}/{c.get('id')}"
            maya = c.get('maya') or {}
            if not maya.get('check_id') or maya.get('severity_report') not in ('S1','S2','S3','S4','Info') or not isinstance(c.get('_scored'),bool):
                errors.append(p+': Maya kontrol/önem/puanlama kaydı eksik; yeniden dönüştürün')
            counts = c.get('counting') or {}
            if counts and counts.get('affected_pages') != (c.get('where') or {}).get('count'):
                errors.append(p+': affected-page count contradicts source counting / Sayfa sayısı kaynak sayımıyla çelişiyor')
            title_text = c.get('title') or ''
            explicit_groups = re.search(r'kaynak.hedef|(?:link|bağlantı)\s+(?:group|gru[pb])|şablon|template',title_text,re.I)
            dom_claim = not explicit_groups and (counts.get('title_unit') == 'DOM occurrences' or not counts.get('template_groups'))
            if dom_claim and isinstance(counts.get('occurrences'),int):
                claim = re.search(r'(?<![\w/])(\d+)\s+(?:link(?:\(s\))?s?|bağlantı(?:nın|da|yı|ya|lar(?:ın|ı|da)?)?)\b', title_text, re.I)
                if claim and int(claim[1]) != counts.get('occurrences'):
                    errors.append(p+': link occurrence count contradicts source / Bağlantı oluşumu sayısı kaynakla çelişiyor; grup ve sayfa sayıları farklı birimlerdir')
            ev = c.get('evidence') or {}
            if ev.get('verified_live') and not verification(c):
                errors.append(p+': tarih tek başına canlı doğrulama değildir; verification kaydı gerekli')
            if ev.get('verification') and len(verification(c)) != len(ev['verification']):
                errors.append(p+': verification URL/kontrol/zaman/yöntem/kanıt/sonuç eksik veya geçersiz')
            if group == 'cards' and (c.get('maya') or {}).get('launch_gated') and not fully_verified(c):
                errors.append(p+': tam kapsam doğrulanmadı; örnek doğrulaması tüm URLleri doğrulamaz, eke taşıyın')
            w = c.get('what_to_write') or {}
            required = ((c.get('maya') or {}).get('source') or {}).get('reader') or 'native'
            for path, leaf in recommendation_leaves(w):
                if not isinstance(leaf, str) or not leaf.strip():
                    continue
                item = w
                m = re.match(r'items\[(\d+)\]',path)
                if m: item = w['items'][int(m.group(1))]
                refs = item.get('derived_from') or (w.get('derived_from') if m else [])
                if m and (not item.get('url') or any(ref.get('url') != item['url'] for ref in refs or [])):
                    errors.append(p+'.what_to_write.'+path+': öneri URLsi ile kanıt URLsi farklı')
                text = reference_text(refs, d.get('page_facts') or {}, required)
                review = item.get('review') or w.get('review') or {}
                if not text:
                    errors.append(p+'.what_to_write.'+path+': exact URL/source/field/read_at kanıtı gerekli; decide veya taslak kullanın')
                    continue
                if review.get('status') != 'reviewed' or not review.get('reviewer') or not timestamp(review.get('reviewed_at')) or not review.get('reason'):
                    errors.append(p+'.what_to_write.'+path+': anlamsal inceleme kaydı gerekli (status/reviewer/reviewed_at/reason)')
                if numbers(leaf) - numbers(text):
                    errors.append(p+'.what_to_write.'+path+': kanıtta olmayan sayısal bilgi')
                lexical = leaf
                if path.endswith('code'):
                    lexical = code_claims(leaf)
                if lexical:
                    new = set(norm_words(lexical)) - set(norm_words(text))
                    if new: errors.append(p+'.what_to_write.'+path+': kanıtta olmayan kelimeler: '+', '.join(sorted(new)))
    for x in (d.get('changes_since_last') or {}).get('fixed',[]):
        r = x.get('resolution') or {}
        scope = x.get('scope') or {}
        urls = set(scope.get('urls') or [])
        if r.get('status') != 'pass' or r.get('check_id') != x.get('check_id') or not urls or scope.get('count') != len(urls) or urls != set(r.get('urls') or []) or not r.get('conditions') or any(not timestamp((r.get('observed_at') or {}).get(u)) for u in urls):
            errors.append('changes_since_last.fixed: karşılaştırılabilir çözülme kanıtı yok; unknown kullanın')
    return errors


def recommendation_leaves(w, path=''):
    if isinstance(w, dict):
        for k,v in w.items():
            p = f'{path}.{k}' if path else k
            if k in ('text','code','proposed') and isinstance(v,str):
                yield p,v
            elif k not in ('review','derived_from'):
                yield from recommendation_leaves(v,p)
    elif isinstance(w,list):
        for i,v in enumerate(w): yield from recommendation_leaves(v,f'{path}[{i}]')


def code_claims(code):
    """Check scalar JSON values, not schema keys; otherwise conservatively check directive values.

    This is lexical consistency, not validation that generated code is safe or semantically correct.
    """
    import json
    try:
        data = json.loads(code)
    except ValueError:
        return re.sub(r'(?i)\b(user-agent|disallow|allow|redirect|return|rewrite|location|https?|www)\b', '', code)
    def values(v):
        if isinstance(v,dict):
            for k,x in v.items():
                if k not in ('@context','@type'): yield from values(x)
        elif isinstance(v,list):
            for x in v: yield from values(x)
        elif isinstance(v,(str,int,float)) and not isinstance(v,bool): yield str(v)
    return ' '.join(values(data))
