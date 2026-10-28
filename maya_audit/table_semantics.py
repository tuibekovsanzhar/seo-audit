"""Conservative, bounded HTML data-table evidence; not a visual/interaction audit."""
import re
from .element_context import Tree


def inspect_tables(html):
    tree = Tree(); tree.feed(html)
    out = []
    tables = list(tree.root.descendants('table'))
    for index, table in enumerate(tables[:200]):
        rows = [r for r in table.descendants('tr') if next((a for a in r.ancestors() if a.tag == 'table'), None) is table]
        cells = [[c for c in r.children if c.tag in ('th', 'td')] for r in rows]
        cells = [r for r in cells if r]
        identity = table.identity() + f' [table {index+1}]'
        layout = table.attrs.get('role') in ('presentation', 'none')
        values = [c.text() for row in cells[1:] for c in row[1:] if c.text()]
        number = re.compile(r"^[+−-]?[0-9][0-9., ]*(?:\s*(?:%|g|mg|kg|ml|l|kj|kcal|EUR|USD|TRY|TL|€|\$|₺))?$", re.I)
        numeric = [v for v in values if number.fullmatch(v) and len(re.sub(r"\D", "", v)) <= 7]
        has_unit = any(re.search(r"(?:%|g|ml|kj|kcal|EUR|USD|TRY|TL|€|\$|₺)$", v, re.I) for v in numeric)
        tabular = (len(cells) >= 2 and all(len(r) >= 2 for r in cells)
                   and ((len(numeric) >= 2 and len(numeric) >= len(values)*0.4) or has_unit))
        complete = tree.complete and len(rows) <= 200 and all(len(r) <= 50 for r in cells)
        for row in cells:
            for cell in row:
                for key in ('rowspan','colspan'):
                    try:
                        complete = complete and 0 < int(cell.attrs.get(key,1)) <= 50
                    except (ValueError,TypeError):
                        complete = False
        headers = [c for row in cells for c in row if c.tag == 'th' or c.attrs.get('role') in ('columnheader', 'rowheader')]
        ids = {c.attrs['id']: c for c in headers if c.attrs.get('id') and c.text()}
        explicit = all(c.attrs.get('headers', '').split() and all(k in ids for k in c.attrs['headers'].split())
                       for row in cells for c in row if c not in headers) if ids else False
        # Compute bounded grid positions, including spans. One scoped header never
        # authorizes unrelated cells/columns. Native headers infer their axis only
        # at a clear edge; explicit IDs/roles remain independently supported.
        positions = []
        occupied = set()
        for ri, row in enumerate(cells[:200]):
            col = 0
            for cell in row[:50]:
                while (ri,col) in occupied:
                    col += 1
                def span(name):
                    try:
                        return max(1,min(50,int(cell.attrs.get(name,1))))
                    except (ValueError,TypeError):
                        return 1
                width,height = span('colspan'),span('rowspan')
                positions.append((cell,ri,col,width,height))
                occupied.update((rr,cc) for rr in range(ri,ri+height) for cc in range(col,col+width))
                col += width
        col_headers, row_headers = [], []
        for cell,ri,col,width,height in positions:
            if cell not in headers or not cell.text():
                continue
            scope,role = cell.attrs.get('scope'),cell.attrs.get('role')
            if scope in ('col','colgroup') or role == 'columnheader' or (not scope and all(c in headers for c in cells[ri])):
                col_headers.append((ri,set(range(col,col+width))))
            if scope in ('row','rowgroup') or role == 'rowheader' or (not scope and col==0):
                row_headers.append((col,set(range(ri,ri+height))))
        data = [(cell,ri,col,width) for cell,ri,col,width,_ in positions if cell not in headers and cell.text()]
        native = bool(data) and all(
            any(hr < ri and set(range(col,col+width)) <= cols for hr,cols in col_headers)
            or any(hc < col and ri in rs for hc,rs in row_headers)
            for cell,ri,col,width in data)
        associated = explicit or native
        out.append({'element': identity, 'rows': len(cells), 'columns': max(map(len, cells), default=0),
                    'layout': layout, 'data_evidence': tabular, 'header_associations': associated,
                    'header_cells': len(headers), 'sample_rows': [[c.text()[:100] for c in r[:6]] for r in cells[:3]],
                    'assessment': 'layout' if layout else 'supported' if associated else 'missing_headers' if tabular else 'uncertain',
                    'parser_complete': complete})
    if len(tables) > 200 or not tree.complete:
        out.append({'element': 'table analysis limit', 'rows': 0, 'columns': 0, 'layout': False,
                    'data_evidence': False, 'header_associations': False, 'header_cells': 0,
                    'sample_rows': [], 'assessment': 'uncertain', 'parser_complete': False})
    return out
