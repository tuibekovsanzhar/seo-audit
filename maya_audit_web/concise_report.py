"""Concise presentation of qualified rows; never mutates or re-judges source findings.

The concise report is the one that goes to a client (and the default printable page, D-23). It says each thing once
(H35): the sentences every finding shares (how to verify a fix, where the complete records are) are explained once
at the head of the section, not on every card; a finding detailed in the priority section is one "↑" cell in the
inventory; notes that imply no action are one line each. Internal decision vocabulary (`recorded_observation`,
launch-gate numbers, "Capped at S4") stays in the full technical export: here an unvalidated rule is "Unverified".
Every finding id still appears, so nothing is dropped, only said once.
"""
from html import escape

from maya_audit.judgments import VERIFY

from .strings import t, current_language

# "Problems by page" rows in the concise report; the rest are in the companion JSON and the full export (CR-13 says 25
# for the Markdown; the concise report also lists every problem by ID, so its page table is a shorter cross-index).
BY_PAGE_ROWS = 12


def _plain(value):
    """A recorded value as words: a list joined, a mapping as "key value" pairs. Never a Python repr (CR-14)."""
    if isinstance(value, dict):
        return ", ".join(f"{k} {_plain(v)}" for k, v in value.items() if v not in (None, "", [], {}))
    if isinstance(value, (list, tuple)):
        return ", ".join(_plain(v) for v in value)
    return str(value)


def _attempt(attempt):
    """One recorded request as one line: "GET 404 · native_crawl · 1234 B · 2026-10-21T12:08Z"."""
    parts = [" ".join(str(attempt[k]) for k in ("method", "status") if attempt.get(k) is not None)]
    parts += [str(attempt[k]) for k in ("source", "url", "location") if attempt.get(k)]
    if attempt.get("body_bytes") is not None:
        parts.append(f"{attempt['body_bytes']} B")
    parts += [str(attempt[k]) for k in ("requested_at", "error") if attempt.get(k)]
    return " · ".join(part for part in parts if part)


def excerpts(record):
    """At most two direct records, explicitly sampled; complete evidence is a companion. Each is a list of
    (label, text) pairs: plain values, never a raw mapping."""
    evidence = (record or {}).get('evidence') or {}
    for key in ('pages','links','tables','grids'):
        entries = evidence.get(key)
        if not isinstance(entries,list):
            continue
        out = []
        for item in entries[:2]:
            if not isinstance(item,dict):
                continue
            short = [(k, _plain(item[k])) for k in ('url','target','element','method','status','body_bytes','requested_at','location','source','repeated_empty','importance') if k in item]
            attempts = [a for a in item.get('attempts') or [] if isinstance(a, dict)]
            if attempts:
                short.append(('attempts', '; '.join(_attempt(a) for a in attempts[:2])))
            if short:
                out.append(short)
        return out
    return []


def _notes(row):
    """The notes a client reads: the engine's severity-cap bookkeeping ("Capped at S4: Hypothesis.") is left out; it is
    in the full technical export. Alternatives added for a qualified judgment have no engine note and are kept."""
    originals = list(row.get('notes') or [])
    shown = list(row.get('notes_shown') or originals)
    originals += [None] * (len(shown) - len(originals))
    return [text for text, original in zip(shown, originals) if not (original or '').startswith('Capped at')]


def _unverified(row, e):
    """A plain label for a rule not yet validated on real sites; the gate numbers stay in the technical export."""
    return f' · <span class="unverified">{e(t("concise.unverified"))}</span>' if row.get('unverified') else ''


def _capped_by_page(table):
    """`practical.by_page` with at most BY_PAGE_ROWS page rows, and a line saying where the rest are."""
    if not table or len(table.get('rows') or []) <= BY_PAGE_ROWS:
        return table
    rest = len(table['rows']) - BY_PAGE_ROWS
    return dict(table, rows=table['rows'][:BY_PAGE_ROWS],
                not_listed=[*table.get('not_listed', []), {'line': t('concise.by_page_more', count=rest)}])


def render(view, rows, generated_at, practical, companions, demo=False):
    from .pdf import CSS, _executive, _by_page
    e = lambda v: escape(str(v if v is not None else ''), quote=True)
    how = view['method']
    out = [f'<!doctype html><html lang="{e(current_language())}"><head><meta charset="utf-8"><meta name="maya-concise" content="50"><style>{CSS}\n.cover{{height:auto}}.issue{{break-inside:auto;border-top:1px solid #aaa;padding-top:8pt}}.issue h3{{break-after:avoid}}a{{color:#174a78;overflow-wrap:anywhere}}thead{{display:table-header-group}}tr{{break-inside:avoid}}.inventory td:first-child{{width:22%}}</style></head><body>',
           f'<h1>{e(view["brand"]["name"])}</h1><p>{e(t("concise.title"))}</p>',
           f'<p>{e(t("concise.scope"))}</p>']
    analysis = (how.get('generation') or {}).get('analysis')
    if analysis:
        out.append('<p><b>'+e(analysis['label'])+'</b> · '+e(analysis['id'])+'</p><p>'+e(t('analysis.notice'))+'</p><p>'+e(t('analysis.source'))+': '+e(analysis['source_audit_id'])+' · '+e(t('analysis.version'))+': '+e(analysis['analysis_version'])+'</p>')
    if demo:
        out.append('<p class="demo">'+e(t('app.demo_banner'))+'</p>')
    out.append('<p>'+e(view.get('site'))+' · '+e(view['brand'].get('country'))+'</p>')
    if practical:
        # The summary flows into the page table, as in the full report: no half-empty page after it.
        out.append(_executive(view, practical, compact=True).replace('<section class="exec">', '<section class="exec flow">', 1))
        out.append(_by_page(_capped_by_page(practical.get('by_page')), view.get('site')))
    from copy import deepcopy
    from .pdf import _data_check
    for check in (view.get('backlinks') or {}).get('checks', []):
        if check.get('check_id') not in ('DFS-4', 'DFS-5'):
            continue
        compact = deepcopy(check)
        shown = 0
        from maya_audit.dataforseo.insights import keyword_counts
        counts = keyword_counts(compact.get("data") or {})
        listed = counts["unique_provider_records"]
        for key in ('table','ambiguous','unrelated','intent_dimensions','editorial_opportunities'):
            table = (compact.get('data') or {}).get(key)
            if isinstance(table,dict) and table.get('rows'):
                table['rows'] = table['rows'][:3]
                shown += len(table['rows'])
        if listed:
            out.append('<p class="small">'+e(t('concise.provider_sample',shown=shown,listed=listed) + ' ' + t('concise.provider_counts', queries=counts['unique_queries'], commercial=counts['confirmed_commercial_candidates'], editorial=counts['editorial_matches'], uncertain=counts['uncertain_candidates']))+'</p>')
            out.append(_data_check(compact))

    from .practical import example_for
    from .wording import note as say
    standard_verification = say(VERIFY)[0]
    # The findings a client acts on first: every problem from Medium up. Low problems are one inventory row each,
    # notes one line each (CR-15, CR-06). An uncertain finding carries its plain "Unverified" label wherever it is.
    important = [r for r in rows if r['requires_fix'] and r['severity'] in ('S1', 'S2', 'S3')]
    shown_above = {r['id'] for r in important}
    out.append(f'<h2>{e(t("concise.priority"))}</h2><p class="small wrap">{e(t("concise.how_to_read"))}</p>')
    if not important:
        out.append(f'<p>{e(t("result.actions.none"))}</p>')
    for row in important:
        out.append(f'<section class="issue" id="{e(row["id"])}"><h3>{e(row.get("title_shown") or row["title"])}</h3>'
                   f'<p class="small">{e(row["id"])} · {e(row["severity_label"])} · {e(row["confidence_label"])} · {e(row["affects"])}{_unverified(row, e)}</p>')
        if row.get('source'):
            out.append('<p class="small">'+e(row['source'].get('label'))+'</p>')
        for label,key in ((t('result.why'),'why'),(t('result.fix'),'fix')):
            out.append(f'<p class="wrap"><b>{e(label)}:</b> {e(row.get(key+"_shown") or row.get(key))}</p>')
        # Only a verification that differs from the one explained at the head of the section (DECISIONS: judgments.VERIFY).
        if row.get('verification') and row['verification'] != standard_verification:
            out.append(f'<p class="wrap">{e(row["verification"])}</p>')
        example = None if (row.get('judgment') or {}).get('qualified') else example_for(row['title'])
        if example:
            out.append('<p class="wrap">'+e(example)+'</p>')
        for text in _notes(row):
            out.append('<p class="small unverified">'+e(text)+'</p>')
        # Evidence limits are already part of `why` (summary.item, CR-18): not said a second time here.
        for line in (row.get('details') or [])[:3]:
            out.append(f'<p class="small wrap">{e(line)}</p>')
        for sample in excerpts(row.get('evidence_record') or {})[:1]:
            out.append('<p class="small wrap">'+e(t('concise.evidence_sample'))+' '+e('; '.join(f'{k}: {v}' for k, v in sample))+'</p>')
        observed = row.get("observed_at") or (row.get('evidence_record') or {}).get("requested_at")
        if observed:
            out.append(f'<p class="small">{e(t("concise.observed"))}: {e(observed)}</p>')
        urls = row.get('sample_pages') or []
        if urls:
            out.append('<ul>'+''.join(f'<li><a href="{e(u)}">{e(u)}</a></li>' for u in urls[:3])+'</ul>')
        out.append('</section>')

    notes = [r for r in rows if not r['requires_fix'] and not r.get('hygiene')]
    if notes:
        out.append(f'<h2>{e(t("concise.notes"))}</h2><p class="small wrap">{e(t("concise.notes_note"))}</p><ul>')
        for row in notes:
            out.append(f'<li class="wrap small">{e(row["id"])} · {e(row.get("title_shown") or row["title"])} · {e(row["affects"])}{_unverified(row, e)}</li>')
        out.append('</ul>')
    # Site-wide hygiene with a fix (G25): after the notes, at most HYGIENE_LINES lines; the rest by ID, so every finding
    # ID still appears.
    from maya_audit.config import HYGIENE_LINES
    hygiene = [r for r in rows if not r['requires_fix'] and r.get('hygiene')]
    if hygiene:
        out.append(f'<h2>{e(t("concise.hygiene"))}</h2><p class="small wrap">{e(t("concise.hygiene_note"))}</p><ul>')
        for row in hygiene[:HYGIENE_LINES]:
            out.append(f'<li class="wrap small">{e(row["id"])} · {e(row.get("title_shown") or row["title"])} · {e(row["affects"])}{_unverified(row, e)}</li>')
        rest = hygiene[HYGIENE_LINES:]
        if rest:
            out.append(f'<li class="wrap small">{e(t("concise.hygiene_more", count=len(rest), ids=", ".join(r["id"] for r in rest)))}</li>')
        out.append('</ul>')

    problems = [r for r in rows if r['requires_fix']]
    out.append(f'<h2>{e(t("concise.inventory"))}</h2><p class="small">{e(t("concise.inventory_note"))}</p><table class="grid inventory"><thead><tr><th>ID</th><th>{e(t("concise.finding"))}</th><th>{e(t("concise.action"))}</th></tr></thead><tbody>')
    for row in problems:
        if row['id'] in shown_above:
            out.append(f'<tr><td class="wrap">{e(row["id"])}</td><td class="wrap" colspan="2">{e(t("concise.above"))}</td></tr>')
            continue
        page = ''.join(f'<br><a href="{e(u)}">{e(u)}</a>' for u in (row.get('sample_pages') or [])[:1])
        example = None if (row.get('judgment') or {}).get('qualified') else example_for(row['title'])
        # Confidence only where it is not "verified": the inventory says what is less than certain, not what is usual.
        confidence = '' if row.get('confidence') == 'verified' else f' · {e(row["confidence_label"])}'
        out.append(f'<tr><td class="wrap">{e(row["id"])}<br>{e(row["severity_label"])}{confidence}{_unverified(row, e)}</td>'
                   f'<td class="wrap">{e(row.get("title_shown") or row["title"])}<br>{e(row["affects"])}{page}</td>'
                   f'<td class="wrap">{e(row.get("fix_shown") or row.get("fix"))}' + (f'<br>{e(example)}' if example else '') + '</td></tr>')
    out.append('</tbody></table>')
    if practical:
        out.append(f'<h2>{e(t("concise.plan"))}</h2>')
        for phase in practical['timeline']:
            if not phase['items']:
                continue
            out.append(f'<h3>{e(phase["label"])}</h3><ul>')
            for item in phase['items']:
                out.append(f'<li class="wrap">{e(item["id"])} · {e(item["what"])} · {e(item["where"])} · {e(item["owner"])} · {e(item["effort"])}</li>')
            out.append('</ul>')
        out.append(f'<h2>{e(t("concise.limits"))}</h2><p>{e(view.get("coverage",{}).get("sampled_note"))}</p>')
        # One line per distinct gap, naming every check it applies to: "pages found but not read" is said once (CR-05).
        gaps = {}
        for area in view.get('areas',[]):
            for check in area['checks']:
                for gap in check.get('not_assessed') or []:
                    text = f'{gap.get("part_shown") or gap.get("part")}: {gap.get("reason_shown") or gap.get("reason")}'
                    gaps.setdefault(text, []).append(check['check_id'])
                # A check that did not run at all, with no gap of its own to say why: its summary says it. A partial
                # check's summary of what it did find is in the full technical export.
                if check['status'] == 'not_assessed' and not check.get('not_assessed'):
                    gaps.setdefault(check.get('summary_shown') or check['summary'], []).append(check['check_id'])
        for text, checks in gaps.items():
            out.append(f'<p class="small wrap">{e(", ".join(dict.fromkeys(checks)))} · {e(text)}</p>')

    out.append(f'<h2>{e(t("concise.provenance"))}</h2>')
    for label,value in ((t('pdf.native_when'), f'{how.get("started_at")} → {how.get("finished_at")}'),
                        (t('pdf.whole_finished'), how.get('whole_job_finished_at') or t('pdf.not_recorded')),
                        (t('concise.processed'), (how.get('generation') or {}).get('processed_at') or t('pdf.not_recorded')),
                        (t('concise.generated'), generated_at),
                        (t('concise.version'), " · ".join(str((how.get('generation') or {}).get(k) or t('pdf.not_recorded')) for k in ('engine_version','source_commit')) )):
        out.append(f'<p class="small wrap"><b>{e(label)}:</b> {e(value)}</p>')
    if practical:
        for source in practical.get('sources',[]):
            # The client copy names the source and what it supplied; the zero-data-retention setting is the operator's
            # and stays in the full technical export (H38).
            out.append(f'<p class="small wrap">{e(source["source"])} · {e(source.get("what_client") or source["what"])} · {e(source["date"])}</p>')
    # File names, not links into the owner's local app (D-08): a client cannot open http://127.0.0.1.
    out.append(f'<h2>{e(t("concise.downloads"))}</h2><p>{e(t("concise.companion_note"))}</p><ul>')
    for kind, name in companions.items():
        out.append(f'<li>{e(t("result.download." + kind))}: {e(name)}</li>')
    out.append('</ul>')
    out.append('</body></html>')
    from maya_audit.report_layout import prepare_tables
    return prepare_tables(''.join(out))
