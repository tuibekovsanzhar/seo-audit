"""The concise client report: at most 10 pages and 15 cards (v0.3 stage 6, DECISIONS 300); never re-judges a finding.

It is the one that goes to a client (and the default printable page, D-23), built from the one selection every client
output shares (`maya_audit.client_selection`): a summary; what Maya could and could not read (its own limits, never
as the client's problems); the top cards in priority order, one card per root cause with an example from each
language; the findings to confirm first ("Teyit edin"); the key pages scorecard; the action plan with quick wins; and a
pointer to the appendix (the XLSX with every finding and affected address) with its counts. It says each thing once
(H35): how to verify a fix is explained at the head of the cards. Internal decision vocabulary (`recorded_observation`,
launch-gate numbers, "not yet validated on real sites") stays in the full technical export and the appendix. Every
number printed carries its unit or label.
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


def _path(url, site=None):
    from urllib.parse import urlsplit
    p = urlsplit(url or "")
    path = (p.path or "/") + (("?" + p.query) if p.query else "")
    return path if path != "/" else (p.netloc or url)


def _when(group, row):
    """This week / this month / later, as the action plan's rule (`practical.when`) for a card: harm first, then how
    small the job is. A card is never "verify first": those findings are in the "Teyit edin" list."""
    severity, effort = group["severity"], (row.get("estimates") or {}).get("effort")
    if severity in ("S1", "S2") or (severity == "S3" and effort == "S"):
        return "week"
    if severity == "S3" or (severity == "S4" and effort == "S"):
        return "month"
    return "later"


def _card_title(group, row, lang):
    """A merge group's own title (DECISIONS 301 (4)) when the card holds more than one finding; else the finding's."""
    from maya_audit.client_selection import MERGE_BY_RULE
    merged = MERGE_BY_RULE.get(group.get("rule_id") or "") if len(group["finding_ids"]) > 1 else None
    return (merged["title"].get(lang) or merged["title"]["en"]) if merged else (row.get("title_shown") or group["title"])


def _score(group):
    """A card's priority score as printed: one decimal, a decimal comma in Turkish (the selection keeps three)."""
    text = f"{group['priority']:.1f}"
    return text.replace(".", ",") if current_language() == "tr" else text


def render(view, rows, generated_at, practical, companions, demo=False, selection=None):
    from .pdf import CSS
    from maya_audit.client_selection import CONFIRM_LINES, platform_steps
    e = lambda v: escape(str(v if v is not None else ''), quote=True)
    how = view['method']
    lang = current_language()
    sel = selection or {"cards": [], "confirm": [], "notes": [], "own_limits": [], "appendix_only": [], "key_pages": [],
                        "coverage": {"lines": []}, "counts": {}, "platform": None}
    by_id = {r['id']: r for r in rows}
    out = [f'<!doctype html><html lang="{e(lang)}"><head><meta charset="utf-8"><meta name="maya-concise" content="10"><style>{CSS}\n'
           '.cover{height:auto}.issue{break-inside:avoid;border-top:1px solid #aaa;padding-top:5pt;margin-top:6pt}'
           '.issue h3{break-after:avoid;margin:0 0 2pt}.issue p{margin:2pt 0}a{color:#174a78;overflow-wrap:anywhere}'
           'thead{display:table-header-group}tr{break-inside:avoid}.score{font-weight:bold}.ex{font-size:9pt}'
           '.c6 td,.c6 th{font-size:9pt;padding:2pt 4pt}</style></head><body>',
           f'<h1>{e(view["brand"]["name"])}</h1><p>{e(t("c6.title"))}</p>',
           f'<p>{e(view.get("site"))} · {e(view["brand"].get("country"))}</p>']
    analysis = (how.get('generation') or {}).get('analysis')
    if analysis:
        # A saved-evidence analysis (the web app's) or an offline rule reassessment (tools/reassess_saved.py): either
        # way no new crawl was made, and the report says so.
        label = analysis.get('label') or (t('c6.reassessed') if analysis.get('kind') == 'offline rule reassessment'
                                          else analysis.get('kind')) or ''
        ident = analysis.get('id') or analysis.get('source_audit_id') or ''
        out.append('<p><b>'+e(label)+'</b> · '+e(ident)+'</p><p>'+e(t('analysis.notice'))+'</p>')
    if demo:
        out.append('<p class="demo">'+e(t('app.demo_banner'))+'</p>')

    # 1. Summary: the outcome, the counts by severity (each labelled), the three cards that come first.
    counts, outcome = view["counts"], view["outcome"]
    out.append(f'<h2>{e(t("pdf.exec.title"))}</h2>')
    block = view.get("blocked")
    if block:  # only a site nothing could read: the first thing a reader needs to know, before any count
        out.append(f'<div class="item lead"><p><b>{e(block["headline"])}</b></p>' + "".join(f'<p class="wrap">{e(line)}</p>' for line in block["lines"])
                   + f"<p><b>{e(t('blocked.next'))}</b></p><ul>" + "".join(f"<li>{e(step)}</li>" for step in block["next_steps"]) + "</ul></div>")
    if view.get("headline"):
        out.append(f'<p class="wrap"><b>{e(view["headline"])}</b></p>')
    out.append(f"<p class=\"wrap\"><b>{e(outcome['label'])}.</b> {e(outcome.get('reason_shown') or outcome['reason'])}</p>")
    out.append('<div class="cards">' + "".join(
        f'<div class="card"><b>{e((sel["counts"].get("by_severity") or counts["by_severity"])[level])}</b>{e(t(f"result.severity.{level}"))}</div>'
        for level in ("S1", "S2", "S3", "S4", "Info")) + "</div>")
    c = sel["counts"]
    out.append('<p class="wrap">' + e(t("c6.summary_counts", findings=c.get("findings", 0), cards=c.get("cards", 0),
                                       confirm=c.get("confirm", 0), notes=c.get("notes", 0),
                                       appendix=c.get("appendix_only", 0))) + '</p>')
    if sel["cards"]:
        out.append(f'<p><b>{e(t("c6.first"))}</b></p><ol>' + "".join(
            f'<li class="wrap">{e(_card_title(g, by_id.get(g["finding_ids"][0]) or {}, lang))} '
            f'<span class="muted small">{e(t("c6.score", score=_score(g)))}</span></li>' for g in sel["cards"][:3]) + '</ol>')

    # 2. Coverage: what was read and what was not. Maya's own limits are said here, never as the client's problems.
    cov = sel["coverage"]
    out.append(f'<h2>{e(t("c6.coverage"))}</h2>')
    out.append('<p class="wrap">' + e(t("c6.coverage_pages", read=cov.get("pages_read") or 0,
                                       known=cov.get("known_not_read") or 0)) + '</p>')
    status = view.get("status")
    if status:
        out.append('<table class="facts c6">' + "".join(
            f'<tr><td>{e(r["label"])}</td><td class="wrap"><b>{e(r["state_label"])}.</b> {e(r["note"])}</td></tr>'
            for r in status["rows"]) + '</table>')
    out.append(f'<p class="small wrap">{e(t("c6.limits_note"))}</p><ul>')
    for line in cov["lines"]:
        if line["kind"] == "page_cap":
            out.append(f'<li class="small wrap">{e(t("c6.limit.page_cap", pages=line.get("pages") or 0, not_read=line.get("not_read") or 0))}</li>')
        elif line["kind"] == "time_budget":
            out.append(f'<li class="small wrap">{e(t("c6.limit.time", seconds=int(line.get("seconds") or 0)))}</li>')
        elif line["kind"] == "reader":
            row = by_id.get((line.get("finding_ids") or [None])[0]) or {}
            out.append(f'<li class="small wrap">{e(row.get("title_shown") or line.get("title"))}</li>')
    # The parts not assessed, in the reader's language: one line per distinct gap with the checks it applies to (CR-05);
    # the three that concern most checks here, the rest counted (all are in the appendix's Coverage sheet).
    gaps = {}
    for area in view.get('areas', []):
        for check in area['checks']:
            for gap in check.get('not_assessed') or []:
                text = f'{gap.get("part_shown") or gap.get("part")}: {gap.get("reason_shown") or gap.get("reason")}'
                gaps.setdefault(text, []).append(check['check_id'])
            if check['status'] == 'not_assessed' and not check.get('not_assessed'):
                gaps.setdefault(check.get('summary_shown') or check['summary'], []).append(check['check_id'])
    ranked = sorted(gaps.items(), key=lambda kv: -len(set(kv[1])))
    for text, checks in ranked[:3]:
        ids = list(dict.fromkeys(checks))
        named = ", ".join(ids[:6]) + (f" +{len(ids) - 6}" if len(ids) > 6 else "")
        out.append(f'<li class="small wrap">{e(named)} · {e(text)}</li>')
    if len(ranked) > 3:
        out.append(f'<li class="small wrap">{e(t("c6.limit.more", count=len(ranked) - 3))}</li>')
    out.append('</ul>')

    # Search and performance (paid panels, when this audit has them): a three-row sample of each keyword table and the
    # lab/field diagnostics, as measured; the complete rows are in the companion JSON.
    from copy import deepcopy
    from .pdf import _data_check
    search = []
    for check in (view.get('backlinks') or {}).get('checks', []):
        if check.get('check_id') not in ('DFS-4', 'DFS-5'):
            continue
        compact = deepcopy(check)
        shown = 0
        from maya_audit.dataforseo.insights import keyword_counts
        kc = keyword_counts(compact.get("data") or {})
        listed = kc["unique_provider_records"]
        for key in ('table', 'ambiguous', 'unrelated', 'intent_dimensions', 'editorial_opportunities'):
            table = (compact.get('data') or {}).get(key)
            if isinstance(table, dict) and table.get('rows'):
                table['rows'] = table['rows'][:3]
                shown += len(table['rows'])
        if listed:
            search.append('<p class="small">' + e(t('concise.provider_sample', shown=shown, listed=listed) + ' ' + t(
                'concise.provider_counts', queries=kc['unique_queries'], commercial=kc['confirmed_commercial_candidates'],
                editorial=kc['editorial_matches'], uncertain=kc['uncertain_candidates'])) + '</p>')
            search.append(_data_check(compact))
    for d in (practical or {}).get('performance_diagnostics') or []:
        search.append(f'<p class="wrap small"><b>{e(d["what"])}</b> · {e(d["fix"])}</p>')
    if search:
        out.append(f'<h2>{e(t("c6.search"))}</h2>' + ''.join(search))

    # 3. The top cards: at most 15, one per root cause, in priority order.
    from .wording import note as say
    standard_verification = say(VERIFY)[0]
    out.append(f'<h2>{e(t("c6.cards", count=len(sel["cards"])))}</h2><p class="small wrap">{e(t("c6.how_to_read"))}</p>')
    if not sel["cards"]:
        out.append(f'<p>{e(t("result.actions.none"))}</p>')
    from maya_audit import language_regions
    from maya_audit.client_selection import MERGE_BY_RULE
    region_names = {r: t("c6.region." + r) for r in language_regions.REGIONS}
    region_names["_percent_first"] = lang == "tr"
    for g in sel["cards"]:
        row = by_id.get(g["finding_ids"][0]) or {}
        est = row.get("estimates") or {}
        merged = MERGE_BY_RULE.get(g.get("rule_id") or "") if len(g["finding_ids"]) > 1 else None
        title = _card_title(g, row, lang)
        out.append(f'<section class="issue" id="card-{g["card"]}"><h3>{g["card"]}. {e(title)}</h3>')
        check = g.get("manual") if (g.get("manual") or {}).get("result") == "confirmed" else None
        confidence = t("c6.class.confirmed", by=check.get("by"), date=check.get("date")) if check else t(f"c6.class.{g['confidence']}")
        affects = t("c6.addresses", count=len(g["urls"])) if merged else (row.get("affects") or "")
        out.append('<p class="small">' + e(" · ".join(x for x in (
            t("c6.score", score=_score(g)), row.get("severity_label") or g["severity"],
            confidence, affects,
            t("c6.effort", effort=est.get("effort_label") or "—"), ", ".join(g["finding_ids"][:3])
            + (f" +{len(g['finding_ids']) - 3}" if len(g["finding_ids"]) > 3 else "")) if x)) + '</p>')
        # A merged card's reason comes from its broadest finding, not from whichever came first (often the homepage).
        why_row = max((by_id.get(i) or {} for i in g["finding_ids"]), key=lambda r: int(r.get("pages_total") or 0)) if merged else row
        out.append(f'<p class="wrap"><b>{e(t("result.why"))}:</b> {e(why_row.get("why_shown") or why_row.get("why") or row.get("why_shown") or row.get("why"))}</p>')
        if check and check.get("note"):
            out.append(f'<p class="wrap"><b>{e(t("c6.manual_note"))}:</b> {e(check["note"])}</p>')
        # A language-mismatch card says which regions are in the other language and bases its steps on them, with the
        # platform's own translation tool (DECISIONS 301 (2)).
        found = next(((by_id.get(i) or {}).get("evidence_record", {}).get("evidence", {}).get("regions")
                      for i in g["finding_ids"] if ((by_id.get(i) or {}).get("evidence_record", {}).get("evidence") or {}).get("regions")), None)
        found = found or next(((m.get("evidence") or {}).get("regions") for m in g.get("members") or [] if (m.get("evidence") or {}).get("regions")), None)
        where = language_regions.line(found, region_names)
        if where:
            out.append(f'<p class="wrap"><b>{e(t("c6.regions"))}:</b> {e(where)}</p>')
        steps = language_regions.advice(found, sel.get("platform"), lang) or platform_steps(g.get("rule_id"), sel.get("platform"), lang)
        if steps:
            label = t("result.fix") + (f" ({sel['platform']})" if sel.get("platform") else "")
            out.append(f'<p class="wrap"><b>{e(label)}:</b> {e("; ".join(steps))}.</p>')
        elif merged:
            out.append(f'<p class="wrap"><b>{e(t("result.fix"))}:</b> {e(merged["fix"].get(lang) or merged["fix"]["en"])}</p>')
        else:
            out.append(f'<p class="wrap"><b>{e(t("result.fix"))}:</b> {e(row.get("fix_shown") or row.get("fix"))}</p>')
        if row.get('verification') and row['verification'] != standard_verification:
            out.append(f'<p class="wrap small">{e(row["verification"])}</p>')
        # The values behind the title (both sides of a price, a brand's names, a link count): at most two lines.
        for line in (row.get('details') or [])[:2]:
            out.append(f'<p class="small wrap">{e(line)}</p>')
        if len(g["finding_ids"]) > 1:
            out.append('<ul class="ex">' + "".join(
                f'<li class="wrap">{e((by_id.get(i) or {}).get("title_shown") or i)}</li>' for i in g["finding_ids"][:4])
                + (f'<li>{e(t("c6.more_findings", count=len(g["finding_ids"]) - 4))}</li>' if len(g["finding_ids"]) > 4 else "")
                + '</ul>')
        if g["examples"]:
            out.append('<p class="ex wrap"><b>' + e(t("c6.examples")) + ':</b> ' + " · ".join(
                (f'{e(x["language"].upper())}: ' if x.get("language") and len(g["languages"]) > 1 else "")
                + f'<a href="{e(x["url"])}">{e(_path(x["url"]))}</a>' for x in g["examples"][:3]) + '</p>')
        for sample in excerpts(row.get('evidence_record') or {})[:1]:
            kept = [(k, v) for k, v in sample if v not in (None, "", "None")]
            if kept:
                out.append('<p class="small wrap">'+e(t('concise.evidence_sample'))+' '+e('; '.join(f'{k}: {v}' for k, v in kept))+'</p>')
        from .pdf import link_cards_html
        out.append(link_cards_html((row.get('link_cards') or [])[:2]))
        out.append('</section>')

    # 4. "Teyit edin": findings to confirm before anyone acts on them; one line each.
    if sel["confirm"]:
        out.append(f'<h2>{e(t("c6.confirm", count=len(sel["confirm"])))}</h2><p class="small wrap">{e(t("c6.confirm_note"))}</p><ul>')
        for g in sel["confirm"][:CONFIRM_LINES]:
            row = by_id.get(g["finding_ids"][0]) or {}
            out.append(f'<li class="wrap small">{e(row.get("title_shown") or g["title"])} · {e(row.get("severity_label") or g["severity"])}'
                       f' · {e(t("c6.reason." + g["confirm_reason"]))} · {e(row.get("affects") or "")}</li>')
        if len(sel["confirm"]) > CONFIRM_LINES:
            out.append(f'<li class="small">{e(t("c6.confirm_more", count=len(sel["confirm"]) - CONFIRM_LINES))}</li>')
        out.append('</ul>')

    # 5. Key pages scorecard: the most important pages read, and what the cards say about each.
    if sel["key_pages"]:
        out.append(f'<h2>{e(t("c6.key_pages"))}</h2><p class="small wrap">{e(t("c6.key_pages_note"))}</p>'
                   f'<table class="grid c6"><thead><tr><th>{e(t("c6.kp.rank"))}</th><th>{e(t("c6.kp.page"))}</th>'
                   f'<th>{e(t("c6.kp.type"))}</th><th>{e(t("c6.kp.importance"))}</th><th>{e(t("c6.kp.cards"))}</th>'
                   f'<th>{e(t("c6.kp.worst"))}</th><th>{e(t("c6.kp.confirm"))}</th></tr></thead><tbody>')
        for p in sel["key_pages"]:
            out.append(f'<tr><td>{e(p["rank"])}</td><td class="wrap">{e(_path(p["url"]))}</td><td>{e(t("c6.type." + str(p["page_type"])))}</td>'
                       f'<td>{e(p["importance"])}</td><td>{e(", ".join(str(n) for n in p["cards"]) or "—")}</td>'
                       f'<td>{e(t("result.severity." + p["worst"]) if p["worst"] else "—")}</td><td>{e(p["confirm"])}</td></tr>')
        out.append('</tbody></table>')

    # 6. Action plan and quick wins: the cards by when, and the small ones.
    out.append(f'<h2>{e(t("c6.plan"))}</h2>')
    plan = {"week": [], "month": [], "later": []}
    for g in sel["cards"]:
        plan[_when(g, by_id.get(g["finding_ids"][0]) or {})].append(g)
    for key in ("week", "month", "later"):
        if plan[key]:
            out.append(f'<p><b>{e(t("c6.when." + key))}:</b> ' + e(", ".join(f'{t("c6.card_ref", n=g["card"])}' for g in plan[key])) + '</p>')
    quick = [g for g in sel["cards"] if ((by_id.get(g["finding_ids"][0]) or {}).get("estimates") or {}).get("effort") == "S"]
    out.append(f'<p><b>{e(t("c6.quick"))}:</b> ' + (e(", ".join(t("c6.card_ref", n=g["card"]) + " " + ((by_id.get(g["finding_ids"][0]) or {}).get("title_shown") or g["title"]) for g in quick))
               if quick else e(t("c6.quick_none"))) + '</p>')

    # 7. The appendix: where everything else is, with its counts.
    out.append(f'<h2>{e(t("c6.appendix"))}</h2><p class="wrap">' + e(t("c6.appendix_line", name=companions.get("xlsx") or "",
               findings=c.get("findings", 0), cards=c.get("cards", 0), confirm=c.get("confirm", 0), notes=c.get("notes", 0),
               appendix=c.get("appendix_only", 0), limits=c.get("own_limits", 0))) + '</p>')
    out.append(f'<p class="small wrap">{e(t("c6.method"))}</p>')
    out.append('<p class="small wrap">' + e(" · ".join(f'{t("result.download." + kind)}: {name}' for kind, name in companions.items())) + '</p>')
    out.append('<p class="small wrap">' + e(" · ".join(str(x) for x in (
        f'{t("pdf.native_when")}: {how.get("started_at")} → {how.get("finished_at")}', f'{t("concise.generated")}: {generated_at}',
        f'{t("concise.version")}: ' + " · ".join(str((how.get('generation') or {}).get(k) or t('pdf.not_recorded')) for k in ('engine_version', 'source_commit')))))
        + '</p>')
    out.append('</body></html>')
    from maya_audit.report_layout import prepare_tables
    return prepare_tables(''.join(out))
