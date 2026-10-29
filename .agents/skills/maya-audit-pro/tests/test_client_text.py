"""Client-facing text: no internal codes, a real address list behind "+N more", page KPI says what it counts."""
import re, sys, json, unittest, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_data as build
import render
from test_export_compat import Wording


def report(urls, whole=0, by_page=()):
    f = {'id': 'STR-2-generic', 'check_id': 'STR-2', 'title': 'Missing heading', 'severity': 'S4', 'confidence': 'estimated',
         'scope': {'kind': 'template', 'count': len(urls), 'urls': urls}, 'how_to_fix': 'Inspect headings',
         'expected': 'Meaningful heading', 'evidence': {}, 'launch_gated': ['LG-42']}
    pages = [{'url': u, 'status': 200} for u in urls]
    return {'checks': [{'findings': [f]}], 'findings_in_priority_order': [f['id']],
            'problem_summary': {'problems': 1, 'by_severity': {'S4': 1},
                                'by_page': [u if isinstance(u, dict) else {'url': u, 'worst_severity': 'S3'} for u in by_page],
                                'whole_site': {'problems': whole}},
            'crawl': {'origin': 'https://sample.example', 'started_at': '2026-10-23T00:00:00+00:00', 'pages': pages},
            'audit_status': {'content_coverage': {'pages_read': len(urls), 'level': 'partial'}}}


def fill(d):
    """Every model field filled with a neutral sentence, so only the rule under test can fail."""
    for s in d['_slots']:
        parts = re.findall(r'[^.\[\]]+', s['path'])
        o = d
        for x in parts[:-1]:
            o = o[int(x)] if x.isdigit() else o[x]
        key = int(parts[-1]) if parts[-1].isdigit() else parts[-1]
        if isinstance(o[key], str) and '⟪' in o[key]:
            o[key] = 'Check the page\nCheck it again' if s.get('lines') else 'Check the page'


def validate(d, r):
    """validate_data.py on `d`, with the report it was built from saved beside it (as build_data records it)."""
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        rp = Path(tmp) / 'report.json'
        rp.write_text(json.dumps(r), encoding='utf-8')
        d = {**d, '_report_path': str(rp)}
        path = Path(tmp) / 'data.json'
        path.write_text(json.dumps(d), encoding='utf-8')
        return subprocess.run([sys.executable, str(Path(build.__file__).with_name('validate_data.py')), str(path)],
                              capture_output=True, text=True, encoding='utf-8')


def build_en(r):
    return build.Builder(r, 'en', render.LABELS['en'], json.loads((build.REFS / 'sahip_efor.json').read_text()),
                         Wording(), None, 'test', False, None).build()


class ClientText(unittest.TestCase):
    def test_no_launch_gate_code_in_client_text_but_kept_in_data(self):
        d = build_en(report(['https://sample.example/a']))
        t = d['todos'][0]
        self.assertNotIn('LG-', t['status'])
        self.assertIn('not yet validated on live sites', t['status'])
        self.assertEqual(t['launch_gated'], ['LG-42'])

    def test_more_addresses_point_at_a_written_address_list(self):
        urls = [f'https://sample.example/p{i}' for i in range(7)]
        d = build_en(report(urls))
        self.assertEqual(d['todos'][0]['more'], 3)
        self.assertNotIn('JSON', render.LABELS['en']['todo_more'] + render.LABELS['tr']['todo_more'])
        with tempfile.TemporaryDirectory() as tmp:
            path = render.write_address_list(d, Path(tmp) / 'r.html')
            rows = path.read_text(encoding='utf-8-sig').splitlines()
        self.assertEqual(rows[0], 'Card,Finding,Severity,Address')
        self.assertEqual(len(rows), 1 + 7)

    def test_no_address_list_when_every_address_is_shown(self):
        d = build_en(report(['https://sample.example/a']))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(render.write_address_list(d, Path(tmp) / 'r.html'))

    def test_page_kpi_names_site_wide_problems_it_does_not_count(self):
        urls = [f'https://sample.example/p{i}' for i in range(5)]
        kpi = next(k for k in build_en(report(urls, whole=3, by_page=urls[:2]))['kpis']
                   if k['label'] == render.LABELS['en']['kpi_problem_pages'])
        self.assertEqual((kpi['value'], kpi['of']), ('2', '5'))
        self.assertEqual(kpi['sub'], 'Page-specific, Low not counted · plus 3 site-wide issues')

    def test_page_kpi_counts_only_pages_with_a_medium_or_higher_problem(self):
        """DECISIONS 283 (2): Carpex showed 145/146 because Low-only pages were counted."""
        urls = [f'https://sample.example/p{i}' for i in range(4)]
        rows = [{'url': urls[0], 'worst_severity': 'S2'}, {'url': urls[1], 'worst_severity': 'S3'},
                {'url': urls[2], 'worst_severity': 'S4'}, {'url': urls[3], 'finding_ids': ['STR-2-generic']}]
        kpi = next(k for k in build_en(report(urls, by_page=rows))['kpis']
                   if k['label'] == render.LABELS['en']['kpi_problem_pages'])
        self.assertEqual((kpi['value'], kpi['of']), ('2', '4'))  # the S4 page and the S4-only saved row are not counted
        self.assertEqual(kpi['sub'], 'Page-specific; Low issues not counted')


if __name__ == '__main__':
    unittest.main()


class InfoCards(unittest.TestCase):
    def info(self, fid, cid, title, urls):
        return {'id': fid, 'check_id': cid, 'title': title, 'severity': 'Info', 'confidence': 'verified',
                'scope': {'kind': 'template', 'count': len(urls), 'urls': urls}, 'evidence': {}}

    def test_info_findings_an_expert_lists_reach_the_pdf_in_two_note_cards(self):
        r = report(['https://sample.example/a'])
        r['checks'].append({'findings': [
            self.info('TSEO-1-x', 'TSEO-1', '75 page(s) load the same analytics tag more than once (possible double counting)',
                      ['https://sample.example/a']),
            self.info('STR-3-v', 'STR-3', '1 page(s) have a VideoObject that looks like an unfilled default', ['https://sample.example/']),
            self.info('STR-10-z', 'STR-10', '9 page(s) have no meta description', ['https://sample.example/b'])]})
        todos = build_en(r)['todos']
        status = {t['status']: t['id'] for t in todos}
        self.assertEqual(status[render.LABELS['en']['perf_card_status']], 'TSEO-1-x')
        self.assertEqual(status[render.LABELS['en']['share_card_status']], 'STR-3-v')
        self.assertFalse(any('STR-10-z' in t['id'] for t in todos))  # not one of the listed kinds

    def test_note_title_names_only_present_topics(self):
        """DECISIONS 278 (T10): a Note card's title names only the topics this report has; the gate checks each one."""
        r = report(['https://sample.example/a'])
        r['checks'].append({'check_id': 'STR-2', 'findings': [], 'observations': [
            {'metric': "pages whose question-and-answer block writes its questions as plain text", 'pages': 1,
             'examples': [{'url': 'https://sample.example/a'}]}]})
        card = next(t for t in build_en(r)['todos'] if t['status'] == render.LABELS['en']['content_card_status'])
        self.assertEqual(card['title'], 'Fix question headings')
        self.assertNotIn('menu', (card['title'] + card['verify']).lower())
        self.assertNotIn('address', (card['title'] + card['verify']).lower())
        self.assertEqual(card['topics'], [{'topic': 'questions', 'ids': ['STR-2']}])
        tr = build.Builder(r, 'tr', render.LABELS['tr'], json.loads((build.REFS / 'sahip_efor.json').read_text()),
                           Wording(), None, 'test', False, None).build()
        card = next(t for t in tr['todos'] if t['status'] == render.LABELS['tr']['content_card_status'])
        self.assertEqual(card['title'], 'Soru başlıklarını düzeltin')
        self.assertNotIn('menü', (card['title'] + card['verify']).lower())

    def test_share_card_title_names_only_present_topics(self):
        r = report(['https://sample.example/a'])
        r['checks'].append({'findings': [
            self.info('STR-3-v', 'STR-3', '1 page(s) have a VideoObject that looks like an unfilled default', ['https://sample.example/'])]})
        card = next(t for t in build_en(r)['todos'] if t['status'] == render.LABELS['en']['share_card_status'])
        self.assertEqual(card['title'], 'Fix video markup')
        self.assertEqual(card['topics'], [{'topic': 'video', 'ids': ['STR-3-v']}])


class Steps(unittest.TestCase):
    def test_a_step_that_starts_with_a_number_keeps_it(self):
        d = build_en(report(['https://sample.example/a']))
        d['todos'][0].update(title='Fix errors', steps='404 pages: link to live addresses\n2. Remove dead links', verify='Check')
        html = render.todo_pages(d, render.LABELS['en'])[0]
        self.assertIn('<li>404 pages: link to live addresses</li>', html)
        self.assertIn('<li>Remove dead links</li>', html)


class Catalogue(unittest.TestCase):
    """DECISIONS 270-271: cards filled from the rule catalogue, an evidence line, and addresses checked per card."""

    def test_a_catalogued_rule_fills_title_steps_and_verify_and_the_evidence_line(self):
        r = report(['https://sample.example/'])
        f = r['checks'][0]['findings'][0]
        f.update(check_id='RND-6', title="The homepage's HTML is 651 KB, above 500 KB", rule_id='rnd6.home_large',
                 evidence={'pages': [{'url': 'https://sample.example/', 'bytes': 651927}], 'threshold_bytes': 500000})
        b = build.Builder(r, 'en', render.LABELS['en'], json.loads((build.REFS / 'sahip_efor.json').read_text()),
                          build.Wording('en', str(Path(__file__).resolve().parents[4])), None, 'test', False, None)
        t = b.build()['todos'][0]
        self.assertEqual(t['title'], 'Slim down the homepage HTML')
        self.assertNotIn('⟪', t['steps'] + t['verify'])
        self.assertEqual(t['fact'], '/ · 651 KB (limit 500 KB)')

    def test_sitemap_step_only_when_an_address_is_in_the_sitemap(self):
        """DECISIONS 278 (T12): a catalogue step with a condition is shown only when the finding's evidence meets it."""
        r = report(['https://sample.example/a'])
        f = r['checks'][0]['findings'][0]
        f.update(check_id='IDX-1', severity='S2', rule_id='idx1.4xx.referenced',
                 title='1 URL(s) return a client error (4xx), linked internally or listed in the sitemap',
                 evidence={'pages': [{'url': 'https://sample.example/a', 'status': 404, 'in_sitemap': False}]})

        def card():
            return build.Builder(r, 'en', render.LABELS['en'], json.loads((build.REFS / 'sahip_efor.json').read_text()),
                                 build.Wording('en', str(Path(__file__).resolve().parents[4])), None, 'test', False,
                                 None).build()['todos'][0]
        t = card()
        self.assertNotIn('sitemap', t['steps'].lower())
        self.assertEqual([s['shown'] for s in t['step_rules']], [False])
        f['evidence']['pages'][0]['in_sitemap'] = True
        t = card()
        self.assertIn('Take the addresses out of the sitemap', t['steps'])

    def test_a_broken_link_card_shows_the_failing_target_apart_from_the_page_to_edit(self):
        """DECISIONS 278: "Failing target URL" and "Affected source pages" are two fields, never swapped."""
        r = report(['https://sample.example/en'])
        f = r['checks'][0]['findings'][0]
        f.update(check_id='IDX-1', severity='S2', rule_id='idx1.4xx.referenced.linked',
                 title='1 URL(s) return a client error (4xx), linked internally or listed in the sitemap; linked from 1 page(s)',
                 evidence={'pages': [{'url': 'https://sample.example/404?from=x', 'status': 404, 'in_sitemap': False}],
                           'target_urls': ['https://sample.example/404?from=x'],
                           'link_sources': [{'source': 'https://sample.example/en', 'links_to': 'https://sample.example/x',
                                             'target': 'https://sample.example/404?from=x'}]},
                 verification={'state': 'confirmed', 'checked': [], 'subjects': ['https://sample.example/en']})
        d = build_en(r)
        t = d['todos'][0]
        self.assertEqual([x['href'] for x in t['links']], ['https://sample.example/en'])
        self.assertEqual(t['target_urls'], ['https://sample.example/404?from=x'])
        html = render.todo_pages(d, render.LABELS['en'])[0]
        self.assertIn('Failing target URL:</b> /404?from=x', html)
        self.assertIn('AFFECTED SOURCE PAGES', html)
        # One line under the status, not two: the evidence line beside it overflowed a real card (Carpex, w13).
        t['fact'] = '/en · /404?from=x · 404'
        html = render.todo_pages(d, render.LABELS['en'])[0]
        self.assertEqual(html.count('class="todo-fact"'), 1)
        self.assertNotIn('/en · /404?from=x · 404', html)
        self.assertNotIn('Take the addresses out of the sitemap', t['steps'] or '')

    def test_a_verify_sentence_is_capitalised_the_turkish_way(self):
        """Carpex w13: "Ilk bayt süresi …", "Iç bağlantılar …" and "Og:site_name …" were printed on client cards."""
        self.assertEqual(build.first_upper('ilk bayt süresi', 'tr'), 'İlk bayt süresi')
        self.assertEqual(build.first_upper('ıslak zemin', 'tr'), 'Islak zemin')
        self.assertEqual(build.first_upper('og:site_name sitenin adını içerir', 'tr'), 'og:site_name sitenin adını içerir')
        self.assertEqual(build.first_upper('<h2>/<h3> başlıkları', 'tr'), '<h2>/<h3> başlıkları')
        self.assertEqual(build.first_upper('internal links', 'en'), 'Internal links')

    def test_an_address_outside_the_card_and_its_evidence_is_refused(self):
        d = build_en(report(['https://sample.example/a']))
        d['todos'][0].update(title='Fix the heading', verify='Check the heading tree on /a.',
                             steps='Fix the heading on /a\nAlso fix /nowhere-in-this-audit')
        for s in d['_slots']:
            if s['path'] not in ('todos[0].title', 'todos[0].steps', 'todos[0].verify'):
                parts = re.findall(r'[^.\[\]]+', s['path'])
                o = d
                for x in parts[:-1]:
                    o = o[int(x)] if x.isdigit() else o[x]
                o[int(parts[-1]) if parts[-1].isdigit() else parts[-1]] = 'Check the page'
        out = validate(d, report(['https://sample.example/a']))
        self.assertIn("'/nowhere-in-this-audit'", out.stdout)
        self.assertNotIn("'/a'", out.stdout)

    def test_no_pdf_when_the_release_gate_cannot_run(self):
        """DECISIONS 278: the skill holds no copy of the gate; without it there is no PDF, with a plain reason."""
        import subprocess
        d = build_en(report(['https://sample.example/a']))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.json'
            path.write_text(json.dumps(d), encoding='utf-8')  # no _report_path: the gate has nothing to read
            out = subprocess.run([sys.executable, str(Path(render.__file__)), str(path), '-o', str(Path(tmp) / 'r.html'),
                                  '--pdf', str(Path(tmp) / 'r.pdf'), '--force'], capture_output=True, text=True, encoding='utf-8')
            self.assertFalse((Path(tmp) / 'r.pdf').exists())
        self.assertNotEqual(out.returncode, 0)
        self.assertIn('Release gate çalıştırılamadığı için PDF üretilmedi.', out.stderr + out.stdout)

    def test_the_validator_reports_the_release_gates_violations(self):
        d = build_en(report(['https://sample.example/a']))
        fill(d)
        d['todos'][0]['all_urls'].append('https://sample.example/not-this-finding')
        out = validate(d, report(['https://sample.example/a']))
        self.assertNotEqual(out.returncode, 0)
        self.assertIn('RG-3: card 1 shows https://sample.example/not-this-finding', out.stdout)
        self.assertIn("Yayın öncesi özet (müşteri PDF'ine girmez)", out.stdout)


class PriorityBox(unittest.TestCase):
    """DECISIONS 275: a priority's two-line text fits its fixed-height row, and a longer one is reported, not cut."""

    def overflow(self, text):
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError:
            self.skipTest('Playwright is not installed')
        d = build_en(report(['https://sample.example/a']))
        d['priorities'] = [{'n': n, 'title': 'Organization block', 'text': text, 'tone': 'high', 'value': '2 pages'}
                           for n in (1, 2, 3)]
        with tempfile.TemporaryDirectory() as tmp:
            html = Path(tmp) / 'r.html'
            html.write_text(render.build_html(d), encoding='utf-8')
            return render.render(html, None)

    def test_a_text_at_the_slot_limit_shows_both_lines(self):
        text = ('The homepage identity block cannot be read, so search engines and AI answers describing the brand '
                'never use it; the fix is short and widely felt.')[:150]
        self.assertEqual([o for o in self.overflow(text) if 'priorities' in o], [])
        # Measured apart from the check: the text's last line ends inside its row (it was cut before 275).
        from playwright.sync_api import sync_playwright
        d = build_en(report(['https://sample.example/a']))
        d['priorities'] = [{'n': 1, 'title': 'Organization block', 'text': text, 'tone': 'high', 'value': '2 pages'}]
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
            html = Path(tmp) / 'r.html'
            html.write_text(render.build_html(d), encoding='utf-8')
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1494, 'height': 1056})
            page.goto(html.resolve().as_uri())
            page.evaluate('document.fonts.ready')
            lines, cut = page.evaluate("""() => { const p = document.querySelector('.pitem .tx p');
                const box = p.closest('.tx').getBoundingClientRect();
                const lh = parseFloat(getComputedStyle(p).lineHeight);
                return [Math.round(p.scrollHeight / lh), p.getBoundingClientRect().bottom > box.bottom + 0.5]; }""")
            browser.close()
        self.assertEqual((lines, cut), (2, False))

    def test_a_third_line_is_reported(self):
        over = self.overflow('The homepage identity block cannot be read by any engine. ' * 5)
        self.assertTrue(any('priorities[0]' in o for o in over), over)


class SecondLook(unittest.TestCase):
    """DECISIONS 276/278: the engine's re-test (schema 1.19 `verification`) is said on the card, and so is its absence."""

    def test_the_card_status_says_what_the_second_look_saw(self):
        r = report(['https://sample.example/a'])
        f = r['checks'][0]['findings'][0]
        f['verification'] = {'state': 'not_reproduced', 'checked': []}
        self.assertIn('Checked again: not reproduced', build_en(r)['todos'][0]['status'])
        f['verification'] = {'state': 'not_retested', 'checked': [], 'reason': 'cap'}
        self.assertNotIn('Checked again', build_en(r)['todos'][0]['status'])
        self.assertIn('Not re-tested', build_en(r)['todos'][0]['status'])

    def test_a_high_card_without_a_retest_says_so(self):
        """T11 on the card: a High finding no second look reached is labelled, never left looking confirmed."""
        r = report(['https://sample.example/a'])
        f = r['checks'][0]['findings'][0]
        f['severity'] = 'S2'
        self.assertIn('Not re-tested', build_en(r)['todos'][0]['status'])
        tr = build.Builder(r, 'tr', render.LABELS['tr'], json.loads((build.REFS / 'sahip_efor.json').read_text()),
                           Wording(), None, 'test', False, None).build()
        self.assertIn('Yeniden sınanmadı', tr['todos'][0]['status'])


REPO = Path(__file__).resolve().parents[4]


def broken_link_report():
    """One broken internal link: /urunler links "Eski ürün" to /eski-urun, which ends at /bulunamadi (404)."""
    base = 'https://sample.example'
    r = report([base + '/urunler'])
    r['schema_version'] = '1.20'
    r['crawl']['pages'] += [{'url': base + '/bulunamadi', 'status': 404}]
    f = r['checks'][0]['findings'][0]
    f.update(check_id='IDX-1', severity='S2', rule_id='idx1.4xx.referenced.linked', confidence='verified',
             title='1 URL(s) return a client error (4xx), linked internally or listed in the sitemap; linked from 1 page(s)',
             evidence={'pages': [{'url': base + '/bulunamadi', 'status': 404, 'in_sitemap': False}],
                       'target_urls': [base + '/bulunamadi'],
                       'link_sources': [{'source': base + '/urunler', 'anchor': 'Eski ürün', 'links_to': base + '/eski-urun',
                                         'target': base + '/bulunamadi'}]},
             verification={'state': 'confirmed', 'checked': [], 'subjects': [base + '/urunler']})
    return r


def build_tr_from_file(r, tmp):
    """build_data.py as the skill runs it: a saved report, the engine from this repository."""
    import subprocess
    rp = Path(tmp) / 'report.json'
    rp.write_text(json.dumps(r, ensure_ascii=False), encoding='utf-8')
    out = Path(tmp) / 'data.json'
    run = subprocess.run([sys.executable, str(Path(build.__file__)), str(rp), '--lang', 'tr', '-o', str(out),
                          '--maya-src', str(REPO)], capture_output=True, text=True, encoding='utf-8')
    assert run.returncode == 0, run.stderr
    return json.loads(out.read_text(encoding='utf-8')), rp


class FinalResult(unittest.TestCase):
    """DECISIONS 283: the client PDF is built from Maya's shared final result and its release gate."""

    def test_the_broken_link_card_shows_where_to_edit_as_a_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            d, _ = build_tr_from_file(broken_link_report(), tmp)
        self.assertEqual(d['_gate_decision'], 'PASS')
        self.assertTrue(d['_digest'])
        [t] = [t for t in d['todos'] if t['id'] == 'IDX-1-generic' or t.get('link_rows')]
        self.assertEqual(t['link_rows'], [{'kind': 'link', 'source_url': 'https://sample.example/urunler',
                                           'link_text': 'Eski ürün', 'links_to': 'https://sample.example/eski-urun',
                                           'target_url': 'https://sample.example/bulunamadi', 'target_status': 404,
                                           'replacement_url': None}])
        html = render.todo_pages(d, render.LABELS['tr'])[0]
        for cell in ('Düzenlenecek sayfa', 'Bağlantı metni', 'Bağlantının adresi', 'Vardığı yer', 'Yeni adres',
                     '<td>/urunler</td>', '<td>Eski ürün</td>', '<td>/eski-urun</td>', '<td>/bulunamadi (404)</td>',
                     '<td>bilinmiyor</td>'):
            self.assertIn(cell, html)
        self.assertNotIn('Hatalı hedef URL', html)  # the table replaces the one-line target

    def test_more_links_than_the_card_shows_are_in_the_address_list(self):
        r = broken_link_report()
        f = r['checks'][0]['findings'][0]
        base = 'https://sample.example'
        for k in range(3):
            f['scope']['urls'].append(f'{base}/sayfa-{k}')
            f['evidence']['link_sources'].append({'source': f'{base}/sayfa-{k}', 'anchor': f'Bağlantı {k}',
                                                  'links_to': base + '/eski-urun', 'target': base + '/bulunamadi'})
        f['scope']['count'] = len(f['scope']['urls'])
        with tempfile.TemporaryDirectory() as tmp:
            d, _ = build_tr_from_file(r, tmp)
            html = render.todo_pages(d, render.LABELS['tr'])[0]
            self.assertIn('+2 bağlantı daha', html)
            path = render.write_address_list(d, Path(tmp) / 'rapor.html')
            text = path.read_text(encoding='utf-8-sig')
        self.assertIn('Bağlantı 2', text)
        self.assertIn('bilinmiyor', text)

    def test_data_built_from_another_state_of_the_report_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            d, rp = build_tr_from_file(broken_link_report(), tmp)
            fill(d)
            r = json.loads(rp.read_text(encoding='utf-8'))
            r['checks'][0]['findings'][0]['severity'] = 'S3'  # the report changed after data.json was built
            out = validate(d, r)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn('şimdiki son sonucundan üretilmemiş', out.stdout)

    def test_a_card_row_for_a_page_its_finding_does_not_list_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            d, rp = build_tr_from_file(broken_link_report(), tmp)
            fill(d)
            [t] = [t for t in d['todos'] if t.get('link_rows')]
            t['link_rows'][0]['source_url'] = 'https://sample.example/baska'
            out = validate(d, json.loads(rp.read_text(encoding='utf-8')))
        self.assertIn('RG-3: card', out.stdout)


class SearchPage(unittest.TestCase):
    """DECISIONS 283 (5): no "search and performance" page when there is no search, lab or field data."""

    def sections(self, d):
        html = render.build_html(d)
        return html.count('<section class="page">'), html

    def test_the_page_is_left_out_without_search_or_lab_data(self):
        d = build_en(report(['https://sample.example/a']))
        fill(d)
        self.assertEqual(d['search']['state'], 'missing')
        self.assertIsNone(d['lab'])
        n, html = self.sections(d)
        self.assertEqual(n, 3 + 1)  # three summary pages and one to-do page
        self.assertNotIn(render.e(render.LABELS['en']['p3_title']), html)
        self.assertIn('04 / 04', html)

    def test_the_page_stays_with_lab_data_only(self):
        d = build_en(report(['https://sample.example/a']))
        fill(d)
        d['lab'] = {'score': 41, 'date': '29 Oct 2026', 'diagnostics': []}
        n, html = self.sections(d)
        self.assertEqual(n, 4 + 1)
        self.assertIn(render.e(render.LABELS['en']['p3_title']), html)
