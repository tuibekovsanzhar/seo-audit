"""Shared static report layout helpers. Generated escaped HTML only; no script execution."""
import re

DRAFT_MARKER = '<meta name="maya-report-state" content="draft">'
DRAFT_WARNING = 'TASLAK — DOĞRULANMADI — MÜŞTERİYE GÖNDERİLMEMELİ'

PRINT_CSS = '''
h2,h3,h4,caption{break-after:avoid;page-break-after:avoid}
h2+p,h3+p,.lead{break-after:avoid;page-break-after:avoid}
body{font-family:Arial,'Noto Sans',sans-serif;font-variant-ligatures:none;font-feature-settings:"liga" 0,"clig" 0}
thead{display:table-header-group;break-inside:avoid;break-after:avoid}
tfoot{display:table-footer-group}
tbody{break-inside:auto}
tr{break-inside:avoid;page-break-inside:avoid}
tbody>tr:first-child{break-before:avoid}
th,td{vertical-align:top}
.schema-type{display:inline-block;white-space:nowrap;word-break:normal;overflow-wrap:normal}
pre.evidence-part{break-inside:avoid;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;font-size:8pt}
.card pre,.card .write{break-inside:auto}
.card>.coverage,.card>p.small{break-after:avoid;page-break-after:avoid}
.card,.card>.coverage{break-inside:avoid;page-break-inside:avoid}
.evidence-identity{break-after:avoid;font-size:9pt}
td[dir=auto]{unicode-bidi:plaintext}
.draft-warning{background:#fff1e8;color:#b42318;text-align:center;font-size:9pt;line-height:1.3;font-weight:bold;padding:2pt;margin-bottom:8pt}
'''


def prepare_tables(html):
    """Use real repeated header groups, including older generated first-row TH tables."""
    def table(match):
        opening, body = match.group(1), match.group(2)
        first = re.match(r'\s*(<tr\b[^>]*>.*?</tr>)(.*)', body, re.S)
        if first and '<th' in first[1] and not re.search(r'<td\b', first[1]):
            body = '<thead>'+first[1]+'</thead><tbody>'+first[2]+'</tbody>'
        return opening+body+'</table>'
    html = re.sub(r'(<table\b[^>]*>)(.*?)</table>', table, html, flags=re.S)
    def direction(match):
        opening, content = match.group(1), match.group(2)
        if re.search('[\u0600-\u06ff]', content) and 'dir=' not in opening:
            opening = opening[:-1]+' dir="auto">'
        return opening+content+'</td>'
    return re.sub(r'(<td\b[^>]*>)(.*?)</td>', direction, html, flags=re.S)


def unique_urls(value, key=None):
    """Only deduplicate set-like URL lists; never collapse repeated DOM observations."""
    if isinstance(value, dict):
        return {k: unique_urls(v, k) for k, v in value.items()}
    if isinstance(value, list):
        if key in ('urls','affected_urls','examples','hrefs','targets') and all(isinstance(v,str) for v in value):
            return list(dict.fromkeys(value))
        return [unique_urls(v) for v in value]
    return value


def evidence_parts(value, limit=1800):
    """Readable continuation blocks with stable identity supplied by the caller; preserve every value."""
    import json
    import textwrap
    text = json.dumps(unique_urls(value), ensure_ascii=False, indent=2)
    lines = [part for line in text.splitlines() for part in (textwrap.wrap(line, 90, replace_whitespace=False, drop_whitespace=False) or [''])]
    parts, current, n = [], '', 0
    for line in lines:
        if current and (len(current)+len(line)>limit or n>=28):
            parts.append(current); current=''; n=0
        current += line+'\n'
        n += 1
    if current:parts.append(current)
    return parts
