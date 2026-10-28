"""Bounded structural context for controls and images; no browser/fetch or semantic truth claims."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
import re

VOID = set('area base br col embed hr img input link meta param source track wbr'.split())


class Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children, self.parts = [], []
        if parent is not None:
            parent.children.append(self)

    def descendants(self, tag=None):
        for child in self.children:
            if tag is None or child.tag == tag:
                yield child
            yield from child.descendants(tag)

    def text(self):
        return ' '.join(' '.join(self.parts + [c.text() for c in self.children]).split())[:1600]

    def ancestors(self):
        node = self.parent
        while node:
            yield node
            node = node.parent

    def identity(self):
        a = self.attrs
        return self.tag + ('#'+a['id'] if a.get('id') else ''.join('.'+c for c in a.get('class', '').split()[:3]))


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('root', [])
        self.stack, self.count, self.complete = [self.root], 0, True

    def handle_starttag(self, tag, attrs):
        if self.count >= 60000 or len(self.stack) >= 150:
            self.complete = False
            return
        # HTML optional cell/list end tags must not turn siblings into descendants.
        if tag in ('li', 'tr', 'td', 'th'):
            for index in range(len(self.stack)-1, 0, -1):
                if self.stack[index].tag == tag:
                    del self.stack[index:]
                    break
                if self.stack[index].tag in ('ul', 'ol', 'table', 'tr'):
                    break
        node = Node(tag, attrs, self.stack[-1]); self.count += 1
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, text):
        if any(n.tag in ('script', 'style', 'noscript', 'template') for n in self.stack):
            return
        if sum(map(len, self.stack[-1].parts)) < 1600:
            self.stack[-1].parts.append(text[:1600])


def enrich(html, analysis, page_url):
    """Retain exact element/component identity and conservative structural equivalence.

    A bounded/incomplete parse may supply observations, but never suppress an image/control finding.
    """
    tree = Tree()
    try:
        tree.feed(html); tree.close()
    except (ValueError, RecursionError):
        tree.complete = False
    if not tree.complete:
        return
    nodes=list(tree.root.descendants('iframe'))
    def walk(n):
        for child in n.children:
            yield child
            yield from walk(child)
    labels={n.attrs['id']:n for n in walk(tree.root) if n.attrs.get('id')}
    for index,(node,frame) in enumerate(zip(nodes, analysis.get('iframes')or[])):
        attrs=node.attrs;refs=(attrs.get('aria-labelledby')or'').split()
        resolved=' '.join(labels[r].text()for r in refs if r in labels).strip()
        name=resolved or (attrs.get('aria-label')or'').strip() or (attrs.get('title')or'').strip()
        frame.update(accessible_name=name or None, name_assessed=True,
            name_source='aria-labelledby'if resolved else 'aria-label'if (attrs.get('aria-label')or'').strip()else 'title'if (attrs.get('title')or'').strip()else None,
            aria_label=attrs.get('aria-label'),aria_labelledby=refs,
            labelledby_resolved={r:labels[r].text()for r in refs if r in labels},
            element_id=node.identity()+':'+str(index+1), role=attrs.get('role'))
    from .analysis import no_address, control_marker, fold_text, _hidden
    for node,frame in zip(nodes,analysis.get('iframes')or[]):
        frame['hidden']=frame.get('hidden',False) or any(_hidden(n.attrs)for n in node.ancestors())
    moved = []
    for node in tree.root.descendants('a'):
        ancestors = list(node.ancestors())
        footer = any(n.tag == 'footer' for n in ancestors)
        why = no_address(node.attrs, footer, page_url)
        if not why or control_marker(node.attrs):
            continue
        text = node.text()[:80]
        record = next((r for r in analysis['dead_links'] if id(r) not in moved and r['text'] == text and r['why'] == why and not r.get('element_id')), None)
        if record is None:
            continue
        parent = next((n for n in ancestors if n.tag == 'li'), node.parent)
        record.update(href=node.attrs.get('href'), element_id=node.identity(), component=parent.identity())
        nested = [n for n in parent.children if n.tag in ('ul', 'ol')]
        children = list(dict.fromkeys(urljoin(page_url or '', a.attrs['href']) for sub in nested for a in sub.descendants('a')
                      if a.attrs.get('href') and not no_address(a.attrs, False, page_url)
                      and urlsplit(urljoin(page_url or '', a.attrs['href'])).scheme in ('', 'http', 'https')))
        if nested and children:
            record.update(control='dropdown parent with crawlable child destinations', child_urls=children[:30],
                          interaction='not_assessed', accessibility='role/name/keyboard require review')
            analysis['link_controls'].append(record); moved.append(id(record))
    analysis['dead_links'] = [r for r in analysis['dead_links'] if id(r) not in moved]
    analysis['dead_link_total'] -= len(moved)
    analysis['link_control_total'] += len(moved)

    images = list(tree.root.descendants('img'))
    available = list(analysis['images'])
    for image_index, node in enumerate(images, 1):
        src = node.attrs.get('data-src') or node.attrs.get('src')
        image = next((i for i in available if i.get('src') == src), None)
        if image is None:
            continue
        available.remove(image)
        image['element_id'] = node.identity() + f':image({image_index})'
        ancestors = list(node.ancestors())
        anchor = next((n for n in ancestors if n.tag == 'a'), None)
        if anchor and not (anchor.text() or anchor.attrs.get('aria-label') or anchor.attrs.get('title')):
            image['functional_unlabelled_link'] = True
        figure = next((n for n in ancestors if n.tag == 'figure'), None)
        caption = next((n.text() for n in figure.children if n.tag == 'figcaption'), '') if figure else ''
        image['presentation_context'] = {'style': node.attrs.get('style'), 'class': node.attrs.get('class'),
            'container_style': node.parent.attrs.get('style'), 'caption': caption,
            'nearby_text': node.parent.parent.text()[:240] if node.parent.parent else '',
            'css_computed': False, 'pixels_reviewed': False}
        image['presentation_context'] = {k: v for k, v in image['presentation_context'].items() if v is False or v}
        if node.attrs.get('role') in ('presentation', 'none') or node.attrs.get('aria-hidden') == 'true':
            image['declared_decorative'] = True
        # Explicitly described informative content, not a file name, figure wrapper or intrinsic size.
        if caption and re.search(r'\b(chart|graph|diagram|grafik|şema|sema|map|harita)\b', caption, re.I):
            image['informative_context'] = caption
            image['presentation_context'].pop('nearby_text', None)  # caption already provides the decision context
        described = node.attrs.get('aria-describedby', '').split()
        if described:
            descriptions = [n.text() for n in tree.root.descendants('*') if n.attrs.get('id') in described]
            image['presentation_context']['associated_description'] = ' '.join(descriptions)
        table = next((n for n in ancestors if n.tag == 'table'), None)
        row = next((n for n in ancestors if n.tag == 'tr'), None)
        if not table or not row or anchor:
            continue
        rows = [n for n in table.descendants('tr') if next((a for a in n.ancestors() if a.tag == 'table'), None) is table]
        at = rows.index(row)
        headers = row.text()
        nutrient = set(re.findall(r'\b(?:enerji|energy|kcal|protein|karbonhidrat|carbohydrate|fat|yag|tuz|sodium|lif|fibre)\b', fold_text(headers)))
        previous = rows[at-1].text() if at else ''
        details = next((n for n in ancestors if n.tag == 'details'), None)
        category = next((n.text() for n in details.children if n.tag == 'summary'), '') if details else ''
        label = category or previous
        following = [r.text() for r in rows[at+1:at+4]]
        # Category illustration in a numeric food table header. Do not infer equivalence from arbitrary prose.
        if (len(nutrient) >= 2 and 1 <= len(label) <= 160 and following
                and sum(len(re.findall(r'\d', t)) for t in following) >= 6
                and not re.search(r'chart|graph|diagram|grafik', src or '', re.I)):
            image.update(beside_label=True, equivalent_text=label,
                         equivalent_text_basis='category label, nutrient column headers and textual numeric rows in the same table',
                         role_assessment='category illustration; structural estimate, not visual certification',
                         table_context={'category': label, 'headers': headers, 'data_sample': following,
                                        'table': table.identity(), 'header_row': at+1})
