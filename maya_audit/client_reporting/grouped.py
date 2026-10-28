"""Compact appendix: one table row per finding, and one block per repair that three or more findings share.

Only the procedure is said once; the members are never merged or dropped: each keeps its own finding ID, title,
addresses and evidence date (CR-10). Full cards, raw evidence and member-by-member qualifications are in the full
export (full=true) and the JSON (CR-12). A card an editor changed is shown whole: its own words may mean something the
generated procedure does not. Nothing here prints a Python value as it is (no dict or list repr, CR-09).
"""
from collections import OrderedDict

# Three findings sharing one repair are a group; two are still easier to read as two rows.
GROUP_MIN = 3


def _addresses(c, site, limit=3):
    from .render_report import E, short_url
    where = c.get('where') or {}
    urls = list(dict.fromkeys(where.get('affected_urls') or where.get('examples') or []))
    shown = ' · '.join(f'<a href="{E(u)}">{E(short_url(u, site))}</a>' for u in urls[:limit])
    total = where.get('count') or len(urls)
    if total and total > min(len(urls), limit):
        shown += f' <span class="small">… ve {E(total - min(len(urls), limit))} adres daha</span>'
    return shown


def _unverified_note(c):
    from .reliability import fully_verified
    gated = any(str(x).startswith('LG-') for x in ((c.get('maya') or {}).get('launch_gated') or []))
    return ('<div class=small>Doğrulanmamış kontrol: elle teyit edilmeden uygulanmamalı.</div>'
            if gated and not fully_verified(c) else '')


def _member_limits(c):
    """Keep each member's consequential uncertainty next to its ID even in a compact row."""
    from .render_report import E
    context = c.get('_source_context') or {}
    notes = list(dict.fromkeys(str(n) for n in context.get('notes') or [] if n))
    if c.get('could_be_intentional'):
        notes.append('Bilinçli bir tercih olabilir; içerik sahibinin amacı doğrulanmalıdır.')
    return ''.join('<div class="small member-qualification">' + E(n) + '</div>' for n in dict.fromkeys(notes))


def row(c, site):
    """One finding as one appendix row: severity, ID and title, addresses, first step."""
    from .render_report import E, T, pill
    count = (c.get('where') or {}).get('count')
    return (f"<tr id=\"finding-{E(c.get('id'))}\"><td>{pill(c.get('severity'))}</td>"
            f"<td><span class=small>{E(c.get('id'))}</span><br>{T(c.get('title'))}{_unverified_note(c)}{_member_limits(c)}</td>"
            f"<td><span class='num'>{E(count or '–')}</span><br>{_addresses(c, site)}</td>"
            f"<td>{T((c.get('steps') or [''])[0])}</td></tr>")


def _group(members, site):
    from .render_report import E, T, pill
    first = members[0]
    p = first['_procedure']
    out = [f'<section data-remediation-group="true" data-subtype="{E(p.get("subtype"))}"><h3>{pill(first["severity"])} '
           f'Ortak uygulama: {T(first.get("title"))} ({len(members)} bulgu)</h3>'
           '<p>Bu bölüm yalnız aynı onarım ve doğrulama işlemini paylaşır; bulgu kimlikleri, adresler ve belirsizlikler '
           'birleştirilmez.</p>',
           f'<p><b>İşlem:</b> {T(p["repair"])}</p><p><b>Doğrulama:</b> {T(p["verification"])}</p><p>{T(p["decision"])}</p>'
           f'<p>Sorumlu: {E(first.get("owner"))} · Efor: {E(first.get("effort"))}</p>',
           '<table><thead><tr><th>Bulgu</th><th>Adresler</th><th>Kanıt tarihi</th></tr></thead><tbody>']
    for c in members:
        read_at = (c.get('evidence') or {}).get('read_at') or 'Mevcut değil'
        out.append(f"<tr id=\"finding-{E(c.get('id'))}\"><td><span class=small>{E(c.get('id'))}</span><br>{T(c.get('title'))}"
                   f"{_unverified_note(c)}{_member_limits(c)}</td><td>{_addresses(c, site)}</td><td class=small>{E(read_at)}</td></tr>")
    out.append('</tbody></table></section>')
    return ''.join(out)


def hygiene_list(cards):
    """Site-wide hygiene notes (G25): one line each, at most config.HYGIENE_LINES, then the rest by ID. Every finding
    keeps its anchor (`finding-<id>`), so a link from a main card still lands."""
    from ..config import HYGIENE_LINES
    from .render_report import E, T
    if not cards:
        return ''
    out = ['<h3>Hijyen</h3><p class="small">Çoğu sitenin olduğu gibi bıraktığı küçük, site genelindeki ayarlar: her '
           'birinin bir düzeltmesi var, hiçbiri acil değil. Tam ayrıntılar JSON ekindedir.</p><ul>']
    for c in cards[:HYGIENE_LINES]:
        out.append(f"<li id=\"finding-{E(c.get('id'))}\" class=small>{E(c.get('id'))} · {T(c.get('title'))} · "
                   f"{E((c.get('where') or {}).get('count') or '–')} adres</li>")
    rest = cards[HYGIENE_LINES:]
    if rest:
        ids = ', '.join(f'<span id="finding-{E(c.get("id"))}">{E(c.get("id"))}</span>' for c in rest)
        out.append(f'<li class=small>{len(rest)} hijyen maddesi daha, kimliğe göre: {ids}</li>')
    return ''.join(out) + '</ul>'


def appendix(cards, site, by_id, start=1):
    """The compact appendix of `cards`, numbered from `start` for the cards shown whole. Hygiene notes (Info with a fix,
    site-wide: findings.is_hygiene) are a short capped list at the end (G25)."""
    from .render_report import card_html
    from .advice import group_signature, edited
    hygiene = [c for c in cards if (c.get('maya') or {}).get('hygiene') and (c.get('maya') or {}).get('severity_report') == 'Info'
               and not edited(c)]
    cards = [c for c in cards if c not in hygiene]
    groups = OrderedDict()
    for index, c in enumerate(cards):
        key = group_signature(c)
        groups.setdefault(key if key is not None else ('separate', index), []).append(c)
    out, rows = [], []

    def flush():
        if rows:
            out.append('<table><thead><tr><th>Önem</th><th>Bulgu</th><th>Adres</th><th>İlk adım</th></tr></thead><tbody>'
                       + ''.join(rows) + '</tbody></table>')
            rows.clear()

    for members in groups.values():
        if len(members) >= GROUP_MIN:
            flush()
            out.append(_group(members, site))
            continue
        for c in members:
            if edited(c):
                flush()
                out.append(card_html(c, start + cards.index(c), site, by_id))
            else:
                rows.append(row(c, site))
    flush()
    return ''.join(out) + hygiene_list(hygiene)
