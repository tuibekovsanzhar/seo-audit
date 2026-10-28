"""The report as a printable page, and as a PDF when a browser is available to print it.

Built from the same adapter (`summary`) as the results page, so the two agree. The page is written on the
server with every value escaped. The PDF is that page printed by headless Chromium (the optional component
the audit also uses to render JavaScript pages) with JavaScript off and every network request refused: the
page needs nothing from outside itself. Fonts are the operating system's own (Helvetica Neue or Arial on
macOS, with Turkish letters); nothing is downloaded.

Chromium adds the page numbers. When Chromium cannot start, `to_pdf` raises `PdfUnavailable` and the app
offers the printable page instead; it does not pretend a PDF exists.
"""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import urlsplit

from maya_audit import launch_gate

from .strings import REVIEW_LINES, current_language, t

from maya_audit.report_layout import PRINT_CSS, prepare_tables

CSS = """
@page{size:A4;margin:16mm 14mm 18mm}
*{box-sizing:border-box}
body{font:10.5pt/1.5 "Helvetica Neue",Helvetica,Arial,"Segoe UI","Noto Sans","DejaVu Sans",sans-serif;color:#1c1c1a;margin:0}
h1{font-size:26pt;line-height:1.15;margin:0 0 6pt}h2{font-size:14pt;margin:20pt 0 6pt;padding-bottom:3pt;border-bottom:1px solid #cfcdc5;break-after:avoid}
h3{font-size:11.5pt;margin:14pt 0 3pt;break-after:avoid}p{margin:3pt 0}ul{margin:3pt 0 3pt 16pt;padding:0}li{margin:2pt 0}
.cover{height:245mm;display:flex;flex-direction:column;justify-content:center;break-after:page}
.cover .kicker{letter-spacing:.12em;text-transform:uppercase;font-size:9pt;color:#5d5b55;margin-bottom:10pt}
.cover table{margin-top:22pt;border-collapse:collapse}.cover td{padding:3pt 18pt 3pt 0;vertical-align:top}
.cover td:first-child{color:#5d5b55}
.muted{color:#5d5b55}.small{font-size:9pt}.demo{border:1.5pt solid #9a5b00;color:#9a5b00;padding:6pt 8pt;margin:10pt 0;font-weight:600}
.cards{display:flex;gap:8pt;margin:10pt 0}.card{flex:1;border:1px solid #cfcdc5;border-radius:5pt;padding:6pt 8pt}
.card b{display:block;font-size:16pt}
.tag{display:inline-block;border-radius:3pt;padding:0 5pt;font-size:8.5pt;font-weight:700;color:#fff;margin-right:5pt}
.unverified{border-left:2pt solid #9a5b00;padding-left:5pt;color:#6b4000}
.S1{background:#b3261e}.S2{background:#c25e00}.S3{background:#8a6d00}.S4{background:#2f6690}.Info{background:#6b7280}
.item{break-inside:avoid;margin:0 0 9pt;padding:6pt 8pt;border:1px solid #e2e0d9;border-radius:5pt}
.url,.wrap{overflow-wrap:anywhere;word-break:break-word}.url{font-family:Menlo,Consolas,"DejaVu Sans Mono",monospace;font-size:8.5pt}
.exec{break-after:page}.exec.flow{break-after:auto}.bypage-sec{break-after:page}.exec h3{margin-top:10pt}.exec ol,.exec ul{margin-top:2pt}
.headline{font-size:15pt;line-height:1.25;font-weight:700;margin:4pt 0 8pt}.cards{margin-top:2pt}.cardlabel{margin:8pt 0 0}
table.bypage{table-layout:fixed}table.bypage td{overflow-wrap:anywhere;word-break:break-word}table.bypage tr{break-inside:avoid}
table.bypage th:nth-child(1){width:27%}table.bypage th:nth-child(2){width:10%}table.bypage th:nth-child(3){width:14%}table.bypage th:nth-child(4){width:49%}
table.facts{width:100%;border-collapse:collapse;margin-top:3pt}table.facts td{padding:2pt 6pt 2pt 0;vertical-align:top}
table.facts td:first-child{width:52pt;color:#5d5b55;font-size:9pt}.covers table.facts td:first-child{width:118pt}code{font-family:Menlo,Consolas,"DejaVu Sans Mono",monospace;font-size:8.5pt;white-space:pre-wrap;overflow-wrap:anywhere}
table.pages{font-size:8.5pt;table-layout:fixed}table.pages td{overflow-wrap:anywhere;word-break:break-word}
table.pages th:nth-child(1){width:19%}table.pages th:nth-child(2){width:5%}table.pages th:nth-child(3){width:24%}table.pages th:nth-child(4){width:20%}table.pages th:nth-child(5){width:7%}table.pages th:nth-child(6){width:18%}table.pages th:nth-child(7){width:7%}
.est{white-space:nowrap}.panel{margin:0 0 10pt}.panel table.grid{margin:3pt 0}table.grid th{font-size:8.5pt;color:#5d5b55}.lead{border:1.5pt solid #9a5b00;background:#fbf6ec}
table.grid{width:100%;border-collapse:collapse;font-size:9.5pt}table.grid td,table.grid th{border-bottom:1px solid #e2e0d9;padding:3pt 6pt 3pt 0;text-align:left;vertical-align:top}
"""
CSS += PRINT_CSS + "\n.bypage-sec{break-after:auto}"


FOOTER = ('<div style="width:100%;font-size:8px;color:#666;padding:0 14mm;display:flex;justify-content:space-between;'
          'font-family:Helvetica,Arial,sans-serif"><span>{title}</span><span><span class="pageNumber"></span> / '
          '<span class="totalPages"></span></span></div>')


class PdfUnavailable(RuntimeError):
    pass


def _e(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def _item(row: dict[str, Any]) -> str:
    pages = "".join(f'<li class="url">{_e(url)}</li>' for url in row["sample_pages"])
    more = row["pages_total"] - len(row["sample_pages"])
    if more > 0:
        pages += f"<li class=\"small\">{_e(t('result.more_pages', count=more))}</li>"
    estimates = row["estimates"]
    return (f'<div class="item"><p class="wrap"><span class="tag {_e(row["severity"])}">{_e(row["severity_label"])}</span>'
            f'<b>{_e(row.get("title_shown") or row["title"])}</b></p>'
            + (f'<p class="wrap small"><b>{_e(row["source"]["label"])}</b>'
               + (f'. {_e(row["source"]["notice"])}' if row["source"].get("notice") else "") + "</p>" if row.get("source") else "") +
            f'<p class="muted small">{_e(row["check_id"])} · {_e(row["affects"])} · {_e(t("result.confidence"))}: '
            f'{_e(row["confidence_label"])}</p>'
            f"<p class=\"wrap\"><b>{_e(t('result.why'))}:</b> {_e(row['why'])}</p>"
            f"<p class=\"wrap\"><b>{_e(t('result.fix'))}:</b> {_e(row.get('fix_shown') or row['fix'])}</p>"
            f'<p class="muted small">{_e(estimates["label"])}: {_e(estimates["owner_label"])}, {_e(estimates["effort_label"])}</p>'
            + (f"<ul>{pages}</ul>" if pages else "") + "</div>")


def _path(url: str, site: str | None) -> str:
    """The page's address within the site ("/privacy"): a table of one site's pages need not repeat its name on every row.
    A page on another host keeps its full address."""
    parts = urlsplit(url)
    home = urlsplit(site or "")
    if home.hostname and parts.hostname and parts.hostname.removeprefix("www.") != home.hostname.removeprefix("www."):
        return url
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def _cell(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return f"{value:,}" if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)


def _schema_types(kinds: list[str]) -> str:
    """The schema types of one page as tags, or a dash. Built outside the f-string so the module parses on Python 3.11."""
    return " ".join('<span class="schema-type">' + _e(kind) + "</span>" for kind in kinds) or "—"


def _data_check(check: dict[str, Any]) -> str:
    """One paid-data check: its sentence, its figures, its table, and where and when the data came from."""
    # Names, sentences and column names as the reader's language has them (`*_shown`); the provider's own cells
    # (class "tp": keywords, domains, addresses, figures) exactly as they came.
    data, shown_as = check.get("data") or {}, check.get("data_shown") or {}
    names, words = shown_as.get("labels") or {}, set(shown_as.get("word_columns") or ())

    def cells(columns: list[Any], row: list[Any]) -> str:
        return "".join(f'<td class="wrap">{_e(names.get(cell, cell))}</td>' if column in words and isinstance(cell, str) else f'<td class="wrap tp">{_e(_cell(cell))}</td>'
                       for column, cell in zip(columns, row))

    out = [f'<div class="panel"><p class="wrap"><b>{_e(check.get("title_shown") or check["title"])}:</b> {_e(check.get("summary_shown") or check["summary"])}</p>']
    metrics = [(label, value) for label, value in (data.get("metrics") or {}).items() if value not in (None, "")]
    if metrics:
        out.append('<table class="grid">' + "".join(f"<tr><td>{_e(names.get(label, label))}</td>" + cells([label], [value]) + "</tr>" for label, value in metrics) + "</table>")
    table = data.get("table") or {}
    if table.get("rows"):
        shown = table["rows"][:TABLE_ROWS]
        out.append('<table class="grid"><tr>' + "".join(f"<th>{_e(names.get(name, name))}</th>" for name in table["columns"]) + "</tr>" + "".join(
            "<tr>" + cells(table["columns"], row) + "</tr>" for row in shown) + "</table>")
        if len(table["rows"]) > len(shown):
            out.append(f'<p class="muted small">{_e(t("result.data.more", count=len(table["rows"]) - len(shown)))}</p>')
    for key in ("ambiguous", "unrelated", "intent_dimensions", "editorial_opportunities"):
        aside = data.get(key) or {}
        if not aside.get("rows"):
            continue
        shown = aside["rows"][:10]
        out.append(f'<p class="wrap small"><b>{_e(names.get(aside["title"], aside["title"]))}: {len(aside["rows"])}.</b> '
                   f'{_e((shown_as.get("notes") or {}).get(key) or aside["note"])}</p><table class="grid"><tr>'
                   + "".join(f"<th>{_e(names.get(name, name))}</th>" for name in aside["columns"]) + "</tr>" + "".join(
                       "<tr>" + cells(aside["columns"], row) + "</tr>" for row in shown) + "</table>")
        if len(aside["rows"]) > len(shown):
            out.append(f'<p class="muted small">{_e(t("result.data.more", count=len(aside["rows"]) - len(shown)))}</p>')
    if check.get("data_from"):
        out.append(f'<p class="muted small">{_e(t("result.data.source", source="DataForSEO " + (check.get("endpoint") or ""), date=str(check["data_from"])[:10], cache=t("result.data.cached" if check.get("from_cache") else "result.data.fresh")))}</p>')
    return prepare_tables("".join(out)) + "</div>"


def _data_panels(view: dict[str, Any]) -> str:
    """Third-party data, apart from the audit's own findings: DataForSEO, real-visitor speed, archived copies."""
    out = []
    backlinks = view.get("backlinks")
    if backlinks:
        out.append(f"<h2>{_e(t('result.backlinks.title'))}</h2><p class=\"muted small\">{_e(t('result.backlinks.note'))}</p>"
                   + (f"<p><strong>{_e(backlinks.get('note_shown') or backlinks['note'])}</strong></p>" if backlinks.get("note") else "")
                   + "".join(_data_check(check) for check in backlinks["checks"]) + f"<p>{_e(backlinks['spent_line'])}</p>")
    speed = view.get("crux")
    if speed:
        out.append(f"<h2>{_e(t('result.crux.title'))}</h2><p class=\"wrap\">{_e(speed.get('summary_shown') or speed['summary'])}</p>")
        if speed.get("metrics"):
            out.append('<table class="grid">' + "".join(
                f"<tr><td class=\"tp\">{_e(row['label'])}</td><td>{_e(row['shown'])}</td><td>{_e(row.get('rating_shown', row['rating']) or '')}</td></tr>" for row in speed["metrics"]) + "</table>")
        if speed.get("status") == "assessed":
            out.append(f'<p class="muted small">{_e(t("result.data.source", source=speed.get("source_shown") or speed["source"], date=speed.get("data_until") or "", cache=""))}</p>')
    archived = view.get("archives")
    if archived:
        out.append(f"<h2>{_e(t('result.archives.title'))}</h2><p class=\"muted small\">{_e(archived.get('notice_shown') or archived['notice'])}</p>")
        for source in archived["sources"]:
            out.append(f"<h3>{_e(source['name'])}: {_e(t('result.archives.pages', count=source['pages_read']))}</h3><ul>" + "".join(
                f'<li class="wrap"><span class="tp">{_e(page.get("title") or page["url"])}</span> <span class="muted small">{_e(page.get("label_shown") or page["label"])}</span></li>' for page in source["pages"])
                + "".join(f'<li class="wrap">[{_e(row["severity"])}] {_e(row["check_id"])} {_e(row.get("title_shown") or row["title"])}</li>' for row in source["findings"])
                + "".join(f'<li class="wrap small muted">{_e(note)}</li>' for note in (source.get("notes_shown") or source["notes"])[:8]) + "</ul>")
    return prepare_tables("".join(out))


TABLE_ROWS = 25


def _reader_lines(reader: dict[str, Any], with_notice: bool = True) -> list[str]:
    """The Firecrawl section's sentences as a person reads them (`lines_shown`), with or without the notice among them."""
    shown = reader.get("lines_shown") or reader["lines"]
    return [said for said, own in zip(shown, reader["lines"]) if with_notice or own != reader.get("notice")]


def _issue(row: dict[str, Any]) -> str:
    """One problem: what, where, why, the exact fix with a short example, who usually does it and how big it is."""
    pages = "".join(f'<li class="url">{_e(url)}</li>' for url in row["pages"])
    more = row["pages_total"] - len(row["pages"])
    if more > 0:
        pages += f"<li class=\"small\">{_e(t('result.more_pages', count=more))}</li>"
    source, unverified = row.get("source"), row.get("unverified")
    return (f'<div class="item"><p class="wrap"><span class="tag {_e(row["severity"])}">{_e(row["severity_label"])}</span><b>{_e(row["what"])}</b></p>'
            + (f'<p class="wrap small"><b>{_e(source["label"])}</b>' + (f'. {_e(source["notice"])}' if source.get("notice") else "") + "</p>" if source else "")
            # A rule not yet validated on real sites: said under the title, before anything is acted on.
            + (f'<p class="wrap small unverified"><b>{_e(unverified["label"])}</b>. {_e(unverified["note"])}</p>' if unverified else "")
            + f'<table class="facts"><tr><td>{_e(t("pdf.where"))}</td><td class="wrap">{_e(row["where"])} <span class="muted small">· {_e(row["check_id"])} · '
              f'{_e(t("result.confidence"))}: {_e(row["confidence"])}</span>' + (f"<ul>{pages}</ul>" if pages else "") + "</td></tr>"
            # Both sides of a price, a brand's names: what the title counts, value by value.
            + (f'<tr><td>{_e(t("detail.title"))}</td><td class="wrap small">' + "<br>".join(_e(line) for line in row["details"]) + "</td></tr>"
               if row.get("details") else "")
            + f'<tr><td>{_e(t("result.why"))}</td><td class="wrap">{_e(row["why"])}</td></tr>'
            + f'<tr><td>{_e(t("result.fix"))}</td><td class="wrap">{_e(row["fix"])}</td></tr>'
            + (f'<tr><td>{_e(t("pdf.example"))}</td><td class="wrap"><code>{_e(row["example"])}</code></td></tr>' if row.get("example") else "")
            + f'<tr><td>{_e(t("pdf.owner"))}</td><td>{_e(row["owner"])} · {_e(row["effort"])} <span class="muted small">({_e(t("result.estimates.label"))})</span></td></tr>'
            + "</table></div>")


def _executive(view: dict[str, Any], practical: dict[str, Any], *, compact: bool = False) -> str:
    """Page one after the cover: what is wrong, what could be gained, what to do first. `compact` (the concise, client
    report) names an unvalidated rule "Unverified" without its launch-gate numbers."""
    counts, outcome, summary = view["counts"], view["outcome"], practical["executive"]
    out = [f'<section class="exec"><h2>{_e(t("pdf.exec.title"))}</h2>']
    block, moved = view.get("blocked"), view.get("redirected")
    if block:  # only a site nothing could read: the first thing a reader needs to know, before any count
        out.append(f'<div class="item lead"><p><b>{_e(block["headline"])}</b></p>' + "".join(f'<p class="wrap">{_e(line)}</p>' for line in block["lines"])
                   + f"<p><b>{_e(t('blocked.next'))}</b></p><ul>" + "".join(f"<li>{_e(step)}</li>" for step in block["next_steps"]) + "</ul></div>")
    if view.get("headline"):  # every problem and every note, before anything else: not only the blockers and the high ones
        out.append(f'<p class="headline wrap">{_e(view["headline"])}</p>')
    if moved:
        out.append(f'<div class="item lead"><p class="wrap">{_e(moved["message"])}</p></div>')
    out.append(f"<p class=\"wrap\"><b>{_e(outcome['label'])}.</b> {_e(outcome.get('reason_shown') or outcome['reason'])}</p>")
    if outcome["note"]:
        out.append(f"<p>{_e(outcome['note'])}</p>")
    # The headline above already says how many pages were checked: here only what could not be checked, and what a sample proves.
    out.append((f"<p>{_e(view['gaps_line'])}</p>" if view.get("gaps_line") else "")
               + (f"<p class=\"muted small\">{_e(view['coverage']['sampled_note'])}</p>" if view['coverage']['sampled_note'] else ""))
    status = view.get("status")
    if status:  # what was read, through whom, and what was not measured: beside the summary, before any count is acted on
        out.append(f'<div class="item covers"><p><b>{_e(status["title"])}</b></p><table class="facts">' + "".join(
            f'<tr><td>{_e(row["label"])}</td><td class="wrap"><b>{_e(row["state_label"])}.</b> {_e(row["note"])}</td></tr>' for row in status["rows"])
            + "</table>" + (f'<p class="wrap small">{_e(status["cache_note"])}</p>' if status.get("cache_note") else "")
            + f'<p class="muted small">{_e(status["duration_line"])}</p></div>')
    out.append(f'<p class="muted small cardlabel">{_e(t("result.by_severity"))}</p><div class="cards">' + "".join(
        f'<div class="card"><b>{_e(counts["by_severity"][level])}</b>{_e(t(f"result.severity.{level}"))}</div>'
        for level in ("S1", "S2", "S3", "S4", "Info")) + "</div>")
    out.append(f"<h3>{_e(summary['problems_title'])}</h3>")
    if summary["problems"]:
        out.append("<ol>" + "".join(f'<li class="wrap"><span class="tag {_e(row["severity"])}">{_e(row["severity_label"])}</span>{_e(row["title"])} '
                                    f'{_chip(row.get("unverified"), compact=compact)}<span class="muted small">{_e(row["where"])}</span>'
                                    + (f'<br><span class="muted small">{_e(row["also"])}</span>' if row.get("also") else "")
                                    + '</li>' for row in summary["problems"]) + "</ol>")
        if summary["more"]:
            # The concise report has no "Findings by area": it points at its own inventory instead.
            more = t("concise.exec.more", total=summary["problems_total"]) if compact else summary["more"]
            out.append(f'<p class="muted small">{_e(more)}</p>')
    else:
        out.append(f"<p>{_e(summary['withheld'] or summary['no_problems'] or t('result.actions.none'))}</p>")
    out.append(f"<h3>{_e(t('pdf.exec.opps'))}</h3>" + ("<ul>" + "".join(f'<li class="wrap">{_e(line)}</li>' for line in summary["opportunities"]) + "</ul>"
               if summary["opportunities"] else f'<p class="muted">{_e(t("pdf.exec.no_opps"))}</p>'))
    out.append(f"<h3>{_e(t('pdf.exec.actions'))}</h3>" + ("<ol>" + "".join(
        f'<li class="wrap">{_e(row["text"])} <span class="muted small">{_e(row["owner"])} · {_e(row["effort"])} · {_e(row["when"])}</span></li>'
        for row in summary["actions"]) + "</ol>" if summary["actions"] else f'<p class="muted">{_e(summary["withheld"] or summary["no_problems"] or "")}</p>'))
    return prepare_tables("".join(out)) + "</section>"


def _chip(unverified: dict[str, Any] | None, *, compact: bool = False) -> str:
    """"Unverified check (LG-22)" after a title on a one-line list (the top problems, the notes), followed by a space; ""
    for a finding with no launch-gate item (DECISIONS 213). A finding whose items are only the bot registry's reasons
    (sentences in English, already in the card's note) shows the label alone. `compact`: the plain "Unverified" label,
    without numbers that mean nothing to a client (H36)."""
    if not unverified:
        return ""
    if compact:
        return f'<span class="unverified small"><b>{_e(t("concise.unverified"))}</b></span> '
    numbers = launch_gate.gate_items(unverified["items"])
    items = f" ({_e(', '.join(numbers))})" if numbers else ""
    return f'<span class="unverified small"><b>{_e(unverified["label"])}</b>{items}</span> '


def _also(view: dict[str, Any]) -> str:
    """". Also fetched: 5 files (PDF or other documents) ..." after the page count, when something fetched was not a page."""
    also = view["pages_stat"].get("also")
    return f". {also}" if also else ""


def _by_page(table: dict[str, Any] | None, site: str | None) -> str:
    """"Problems by page": one row for the whole site, then one for each page with a problem, saying what is wrong on that
    page (`lines`). Nothing when there is none."""
    if not table:
        return ""
    def continued(rows):
        # Keep URL/group identity on each bounded continuation row. The total is shown once,
        # rather than making split presentation rows look like additional affected pages/problems.
        out = []
        for row in rows:
            lines = row.get('lines') or row.get('titles') or []
            chunks = [lines[i:i+4] for i in range(0,len(lines),4)] or [[]]
            for index, chunk in enumerate(chunks):
                part = dict(row, lines=chunk)
                if index:
                    part['problems'] = '…'
                    if part.get('whole_site'):
                        part['label'] += f' ({index+1}/{len(chunks)})'
                    else:
                        part['continuation'] = f' ({index+1}/{len(chunks)})'
                out.append(part)
        return out
    out = [f"<h2>{_e(table['title'])}</h2>"]
    if table["rows"]:
        out.append('<table class="grid bypage"><tr>' + "".join(f"<th>{_e(name)}</th>" for name in table["columns"]) + "</tr>" + "".join(
            "<tr>" + (f'<td class="wrap"><b>{_e(row["label"])}</b></td>' if row["whole_site"] else f'<td class="url">{_e(_path(row["url"], site))}{_e(row.get("continuation", ""))}</td>')
            + f'<td>{row["problems"]}</td><td><span class="tag {_e(row["worst_severity"])}">{_e(row["worst_severity_label"])}</span></td>'
            + '<td class="wrap">' + "<br>".join(_e(line) for line in row.get("lines") or row["titles"]) + "</td></tr>" for row in continued(table["rows"])) + "</table>")
    out += [f'<p class="wrap small">{_e(entry["line"])}</p>' for entry in table["not_listed"]]
    files = table.get("files") or {}
    if files.get("rows"):  # sitemaps, robots.txt, documents: not pages, so under the table and never in it
        out.append(f'<h3>{_e(files["title"])}</h3><table class="grid bypage files"><tr>' + "".join(f"<th>{_e(name)}</th>" for name in files["columns"]) + "</tr>" + "".join(
            f'<tr><td class="url">{_e(_path(row["url"], site))}{_e(row.get("continuation", ""))}</td><td>{row["problems"]}</td>'
            f'<td><span class="tag {_e(row["worst_severity"])}">{_e(row["worst_severity_label"])}</span></td>'
            + '<td class="wrap">' + "<br>".join(_e(line) for line in row["lines"]) + "</td></tr>" for row in continued(files["rows"])) + "</table>")
    out.append(f'<p class="muted small">{_e(table["note"])}</p>')
    return prepare_tables("".join(out))


def render_full_html(view: dict[str, Any], *, rows: list[dict[str, Any]], plan: dict[str, Any], generated_at: str,
                demo: bool = False, practical: dict[str, Any] | None = None) -> str:
    """One self-contained HTML document: the practical report.

    `view` is summary.build, `rows` every finding (summary.search), `plan` summary.action_plan, and `practical` is
    practical.build for the same audit (built here without its page table when the caller has none)."""
    if practical is None:
        from . import practical as practical_module

        practical = practical_module.build(view, rows, {"crawl": {"pages": [], "requests": [], "user_agent": view["method"].get("user_agent"),
                                                                  "started_at": view["method"].get("started_at"),
                                                                  "finished_at": view["method"].get("finished_at")}, "checks": []}, None)
    counts, outcome, how, brand = view["counts"], view["outcome"], view["method"], view["brand"]
    single = view.get("single_page")  # a single-page audit: its title names the one address that was read
    title = single["title"] if single else f"{t('app.title')}: {brand['name']}"
    language = current_language()  # the page says which language it is written in
    out = [f'<!doctype html><html lang="{_e(language)}"><head><meta charset="utf-8">', f"<title>{_e(title)}</title><style>{CSS}</style></head><body>"]

    # Cover
    out.append(f'<section class="cover"><div class="kicker">{_e(t("pdf.kicker"))}</div><h1 class="wrap">{_e(brand["name"])}</h1>')
    if single:
        out.append(f'<p class="wrap"><b>{_e(single["title"])}</b></p><p class="muted small">{_e(single["note"])}</p>')
    if view.get("start_address"):  # the address typed answered with an error: said on the cover, before any figure
        out.append(f'<p class="wrap"><b>{_e(view["start_address"]["message"])}</b></p>')
    if brand["label"]:
        out.append(f'<p class="muted small">{_e(brand["label"])}</p>')
    if demo:
        out.append(f'<p class="demo">{_e(t("app.demo_banner"))}</p>')
    out.append("<table>" + "".join(f"<tr><td>{_e(label)}</td><td class=\"wrap\">{_e(value)}</td></tr>" for label, value in (
        (t("pdf.site"), view["site"]), *([(t("pdf.country"), brand["country"])] if brand.get("country") else []),
        (t("pdf.date"), (how["started_at"] or "")[:10]),
        ((view["pages_stat"]["label"], f'{view["pages_stat"]["value"]} ({view["pages_stat"]["detail"]})' + _also(view)) if view["pages_stat"]["blocked"] or view["pages_stat"].get("reader")
         else (t("result.pages"), t("pdf.pages_of_cap", pages=counts["pages_checked"], cap=how["page_cap"]) + _also(view))),
        (t("pdf.outcome"), outcome["label"]))) + "</table>"
        # A translation that no native speaker has reviewed says so on the cover (never on the English report).
        + (f'<p class="muted small review-note">{_e(REVIEW_LINES[language])}</p>' if language in REVIEW_LINES else "") + "</section>")

    # 1. Executive summary: one page
    out.append(_executive(view, practical))
    # Which page each problem is on: right after the summary that counts them.
    # "Problems by page" follows the summary directly: the summary's page break moves to the end of the table, so a
    # summary that runs a few lines onto a new page does not leave the rest of that page empty.
    by_page = _by_page(practical.get("by_page"), view["site"])
    if by_page:
        out[-1] = out[-1].replace('<section class="exec">', '<section class="exec flow">', 1)
        out.append(f'<section class="bypage-sec">{by_page}</section>')
    block = view.get("blocked")
    if block and block.get("allowlist"):
        allow = block["allowlist"]
        out.append(f'<div class="item"><p><b>{_e(allow["title"])}</b></p><p class="small wrap">{_e(allow["note"])}</p>' + "".join(
            f'<p><b>{_e(item.get("title_shown") or item["title"])}</b></p><ol>' + "".join(f'<li class="wrap small">{_e(step)}</li>' for step in item.get("steps_shown") or item["steps"]) + "</ol>"
            for item in allow["blocks"]) + "</div>")
    owned = view.get("ownership")
    if owned:
        out.append(f'<div class="item"><p><b>{_e(t("verify.title"))}</b></p><p class="wrap">{_e(owned.get("summary_shown") or owned["summary"])}</p>'
                   + ("" if owned["verified"] else "<ul>" + "".join(f'<li class="wrap small">{_e(line)}</li>' for line in owned.get("instructions_shown") or owned["instructions"]) + "</ul>") + "</div>")
    reader = view.get("firecrawl")
    if reader and not (reader.get("main_reader") and reader["used"]):  # an unusual use of the reader is said before any finding that rests on it
        title_line = t("fc.result.title") if reader["used"] else t("fc.result.not_used")
        out.append(f'<div class="item lead"><p><b>{_e(title_line)}</b></p>'
                   + (f'<p class="wrap"><b>{_e(reader.get("notice_shown") or reader["notice"])}</b></p>' if reader["used"] and reader.get("notice") else "")
                   + (f'<p class="wrap"><b>{_e(reader["decision"]["message"])}</b></p>' if reader.get("decision") else "")
                   + "".join(f'<p class="wrap">{_e(line)}</p>' for line in _reader_lines(reader, with_notice=False)) + "</div>")

    # 2. Scorecard
    out.append(f"<h2>{_e(t('pdf.scorecard'))}</h2><p class=\"muted small\">{_e(t('pdf.scorecard.note'))}</p><table class=\"grid\"><tr>" + "".join(
        f"<th>{_e(t(key))}</th>" for key in ("pdf.col.area", "pdf.col.checks", "pdf.col.in_order", "result.severity.S1", "result.severity.S2",
                                              "result.severity.S3", "result.severity.S4", "pdf.col.notes", "pdf.col.not_checked")) + "</tr>" + "".join(
        f'<tr><td>{_e(row["label"])}</td><td>{row["checks"]}</td><td>{row["in_order"]}</td>' + "".join(
            f'<td>{row["by_severity"][level] or "–"}</td>' for level in ("S1", "S2", "S3", "S4")) + f'<td>{row["notes"] or "–"}</td><td>{row["not_checked"] or "–"}</td></tr>'
        for row in practical["scorecard"]) + "</table>")

    # 3. Action plan as a timeline
    out.append(f"<h2>{_e(t('pdf.timeline'))}</h2><p class=\"muted small\">{_e(plan['estimates_note'])}</p>")
    if not any(step["items"] for step in practical["timeline"]):
        out.append(f"<p>{_e(t('result.actions.none'))}</p>")
    for step in practical["timeline"]:
        if not step["items"]:
            continue
        out.append(f"<h3>{_e(step['label'])} ({len(step['items'])})</h3><p class=\"muted small\">{_e(step['note'])}</p><table class=\"grid\">" + "".join(
            f'<tr><td><span class="tag {_e(r["severity"])}">{_e(r["severity_label"])}</span></td>'
            f'<td class="wrap">{_e(r["what"])}<br><span class="muted small">{_e(r["check_id"])} · {_e(r["where"])}</span></td>'
            f'<td class="small est">{_e(r["owner"])}<br>{_e(r["effort"])}</td></tr>' for r in step["items"]) + "</table>")

    # 4. Every issue
    out.append(f"<h2>{_e(t('pdf.findings_by_area'))}</h2>")
    if not practical["issues"]:
        out.append(f"<p>{_e(t('result.actions.none'))}</p>")
    for area in view["areas"]:
        mine = [row for row in practical["issues"] if row["area"] == area["area"]]
        if mine:
            out.append(f"<h3>{_e(area['label'])}</h3>" + "".join(_issue(row) for row in mine))
    # Notes, then site-wide hygiene with a fix (G25: not "nothing to fix"); the full print lists every hygiene row.
    for key, kept in (("pdf.notes", [row for row in rows if not row["requires_fix"] and not row.get("hygiene")]),
                      ("concise.hygiene", [row for row in rows if not row["requires_fix"] and row.get("hygiene")])):
        if kept:
            out.append(f"<h3>{_e(t(key))}</h3><ul>" + "".join(
                f'<li class="wrap">{_e(row.get("title_shown") or row["title"])} {_chip(row.get("unverified"))}<span class="muted small">{_e(row["check_id"])}</span></li>'
                for row in kept) + "</ul>")
    if view["review"]:
        out.append(f"<h2>{_e(t('result.review.title'))}</h2>" + "".join(
            f'<div class="item"><p class="wrap"><b>{_e(r.get("title_shown") or r["title"])}</b> <span class="muted small">{_e(r["check_id"])}</span></p>'
            f"<p class=\"wrap\">{_e(r.get('why_shown') or r['why'])} {_e(r.get('action_shown') or r['action'])}</p>"
            + ('<p class="wrap small">' + "<br>".join(_e(line) for line in r["details"]) + "</p>" if r.get("details") else "") + "</div>" for r in view["review"]))

    # 5. Every page
    pages = practical["pages"]
    if pages["rows"]:
        out.append(f"<h2>{_e(t('pdf.pages'))} ({pages['total']})</h2><p class=\"muted small\">{_e(pages['note'])}</p><table class=\"grid pages\"><tr>" + "".join(
            f"<th>{_e(t(key))}</th>" for key in ("pdf.col.page", "pdf.col.status", "pdf.col.title", "pdf.col.h1", "pdf.col.words", "pdf.col.schema", "pdf.col.issues"))
            + "</tr>" + "".join(
            f'<tr><td class="url">{_e(_path(row["url"], view["site"]))}</td><td>{_e(_cell(row["status"]))}</td><td class="wrap tp">{_e(_cell(row["title"]))}</td>'
            f'<td class="wrap tp">{_e(_cell(row["h1"]))}{" (+" + str(row["h1_count"] - 1) + ")" if row["h1_count"] > 1 else ""}</td>'
            f'<td>{_e(_cell(row["words"]))}{"+" if row["words_cut"] else ""}</td><td class="small schema-types">{_schema_types(row["schema"])}</td>'
            f'<td>{row["issues"] or "–"}</td></tr>' for row in pages["rows"]) + "</table>")

    # 6. Data panels
    out.append(_data_panels(view))

    # 7. What else we checked
    if practical["passed"]:
        out.append(f"<h2>{_e(t('pdf.passed'))}</h2><p class=\"muted small\">{_e(t('pdf.passed.note'))}</p>" + "".join(
            f"<h3>{_e(area['label'])}</h3><ul>" + "".join(
                f'<li class="wrap"><b>{_e(c["check_id"])} {_e(c.get("title_shown") or c["title"])}.</b> <span class="small">{_e(c.get("summary_shown") or c["summary"])}</span></li>' for c in area["checks"]) + "</ul>"
            for area in practical["passed"]))
    if view["answers"]["checks"]:
        out.append(f"<h3>{_e(t('result.answers.title'))}</h3><p class=\"muted small\">{_e(view['answers']['note'])}</p><ul>" + "".join(
            f"<li class=\"wrap\"><b>{_e(c['check_id'])} {_e(c.get('title_shown') or c['title'])}</b> ({_e(c['status_label'])}): {_e(c.get('summary_shown') or c['summary'])}</li>"
            for c in view["answers"]["checks"]) + "</ul>")

    # What could not be checked
    coverage = view["coverage"]
    out.append(f"<h2>{_e(t('result.coverage.title'))}</h2>")
    lines = [f"<li class=\"wrap\"><b>{_e(g.get('part_shown') or g['part'])}</b> <span class=\"muted small\">{_e(g['checks_label'])}</span>"
             f"<br>{_e(g.get('reason_shown') or g['reason'])}</li>" for g in coverage["gaps"]]
    if coverage["read_only_note"]:
        lines.insert(0, f"<li>{_e(coverage['read_only_note'])}</li>")
    if coverage["resumed_note"]:
        lines.insert(0, f"<li>{_e(coverage['resumed_note'])}</li>")
    out.append(f"<ul>{''.join(lines)}</ul>" if lines else f"<p>{_e(t('result.coverage.none'))}</p>")
    if coverage.get("skipped_note"):  # what the time limit cut (DECISIONS 219)
        out.append(f"<p class=\"wrap\">{_e(coverage['skipped_note'])}</p>")

    # 8. Technical appendix: sources and dates, how the audit ran
    from maya_audit.report_layout import evidence_parts
    generation = how.get('generation') or {'engine_version':'not recorded in historical report', 'native_finished_at':how.get('finished_at')}
    generation = dict(generation, whole_job_finished_at=how.get('whole_job_finished_at') or 'not recorded', schema_version=how.get('schema_version'))
    out.append('<h2>'+_e(t('pdf.provenance'))+'</h2><p>'+_e(t('pdf.provenance.note'))+'</p>')
    for part in evidence_parts(generation):
        out.append('<pre class="evidence-part">'+_e(part)+'</pre>')
    out.append('<h3>'+_e(t('pdf.finding_evidence'))+'</h3><p>'+_e(t('pdf.finding_evidence.note'))+'</p>')
    for row in rows:
        if not row.get('evidence_record'):
            continue
        from copy import deepcopy
        record = deepcopy(row['evidence_record'])
        judgment = (record.get('evidence') or {}).get('judgment')
        if judgment:
            record['evidence'].pop('judgment', None)
            record['evidence']['qualified_decision_reference'] = 'Companion JSON: evidence.judgment'
        parts = evidence_parts(record)
        for index, part in enumerate(parts, 1):
            out.append('<h4 class="evidence-identity">'+_e(row['id'])+' · '+_e(row.get('title_shown') or row['title'])+' · '+str(index)+'/'+str(len(parts))+'</h4><pre class="evidence-part">'+_e(part)+'</pre>')
    out.append(f"<h2>{_e(t('pdf.appendix'))}</h2><h3>{_e(t('pdf.sources'))}</h3><table class=\"grid\"><tr>" + "".join(
        f"<th>{_e(t(key))}</th>" for key in ("pdf.col.source", "pdf.col.what", "pdf.col.date")) + "</tr>" + "".join(
        f'<tr><td class="wrap">{_e(row["source"])}</td><td class="wrap">{_e(row["what"])}</td><td class="small">{_e(row["date"])}</td></tr>'
        for row in practical["sources"]) + "</table>")
    spend = view.get("spend") or {}
    costs = []
    if spend.get("dataforseo"):
        costs.append(t("status.spend.dataforseo", cost=f"{spend['dataforseo']['cost_usd'] or 0:.4f}", estimate=f"{spend['dataforseo']['estimated_usd'] or 0:.4f}",
                       possibly=spend["dataforseo"]["possibly_billed"], cached=spend["dataforseo"]["from_cache"]))
    if spend.get("firecrawl"):
        costs.append(t("status.spend.firecrawl", credits=f"{spend['firecrawl']['credits'] or 0:g}", estimate=f"{spend['firecrawl']['estimated_max_credits'] or 0:g}",
                       possibly=spend["firecrawl"]["possibly_billed"], cached=spend["firecrawl"]["from_cache"], zdr=spend["firecrawl"].get("zero_data_retention_shown") or spend["firecrawl"]["zero_data_retention"] or "—",
                       usd=t("status.spend.usd.known", usd=f"{spend['firecrawl']['usd'] or 0:.4f}") if spend["firecrawl"]["usd_known"] else t("status.spend.usd.unknown")))
    if costs:
        out.append(f"<h3>{_e(t('status.spend.title'))}</h3>" + "".join(f'<p class="wrap small">{_e(line)}</p>' for line in costs))
    if reader and reader.get("main_reader") and reader["used"]:
        out.append(f"<h3>{_e(t('fc.result.title'))}</h3>" + "".join(f'<p class="wrap small">{_e(line)}</p>' for line in _reader_lines(reader)))
    out.append(f"<h3>{_e(t('result.technical.title'))}: {_e(t('result.gates.title'))}</h3><ul>" + "".join(
        f"<li class=\"wrap\"><b>{_e(g['check_id'])} {_e(g.get('title_shown') or g['title'])}: {_e(g.get('state_label') or g['state'])}.</b> {_e(g.get('summary_shown') or g['summary'])}</li>"
        for g in view["gates"]) + "</ul>")
    sources = [t(f"pdf.source.{name}") for name, used in how["optional_sources"].items() if used]
    facts = ((t("pdf.method.start"), how["start_url"]), (t("pdf.native_when"), f"{how['started_at']} → {how['finished_at']}"),
             (t("pdf.whole_finished"), how.get("whole_job_finished_at") or t("pdf.not_recorded")),
             (t("pdf.method.cap"), t("pdf.pages_of_cap", pages=how["pages_checked"], cap=how["page_cap"])),
             (t("pdf.method.requests"), t("pdf.method.requests.value", requests=how["requests"], redirects=how["redirects"])),
             (t("pdf.method.delay"), t("pdf.method.delay.value", seconds=how["request_delay_s"])),
             (t("pdf.method.rendering"), how["rendering"]["label"] + (f" ({how['rendering'].get('reason_shown') or how['rendering']['reason']})" if how["rendering"]["reason"] else "")),
             (t("pdf.method.sources"), ", ".join(sources) or t("pdf.method.sources.none")),
             (t("pdf.method.stop"), how.get("stop_shown") or f"{how['stop_reason']}: {how['stop_detail']}"),
             (t("pdf.method.identity"), how["user_agent"]), (t("pdf.method.generated"), generated_at))
    steps = coverage.get("steps")
    if steps and steps["rows"]:  # how long each step took (DECISIONS 219)
        out.append(f"<h3>{_e(steps['title'])}</h3><table class=\"grid\"><tr>" + "".join(f"<th>{_e(name)}</th>" for name in steps["columns"])
                   + "</tr>" + "".join(f"<tr><td class=\"wrap\">{_e(row['label'])}</td><td>{_e(row['time'])}</td><td>{_e(row['requests'])}</td>"
                                        f"<td>{_e(row['waiting'])}</td></tr>" for row in steps["rows"]) + "</table>")
    out.append(f"<h3>{_e(t('pdf.method'))}</h3><table class=\"grid\">" + "".join(
        f"<tr><td>{_e(label)}</td><td class=\"wrap\">{_e(value)}</td></tr>" for label, value in facts) + "</table>")
    out.append(f"<p class=\"small muted\">{_e(t('pdf.method.limits'))}</p></body></html>")
    return prepare_tables("".join(out))


def to_pdf(html: str, *, footer_title: str = "", max_pages: int | None = None) -> bytes:
    """Print `html` to PDF with headless Chromium. PdfUnavailable when there is no browser to do it."""
    if ('name="maya-concise"' in html or 'name="maya-client-compact"' in html) and max_pages is None:
        max_pages = 50
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PdfUnavailable("Playwright is not installed") from exc
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                context = browser.new_context(java_script_enabled=False, offline=True, accept_downloads=False)
                context.route("**/*", lambda route: route.abort())
                page = context.new_page()
                from maya_audit.report_layout import DRAFT_MARKER, DRAFT_WARNING
                header = "<span></span>"
                if DRAFT_MARKER in html:
                    # Chromium clips negative fixed positions. Use its reserved margin header,
                    # outside the content box, rather than painting over continuation headings.
                    html = html.replace('</head>', '<style>@media print{.draft-warning{display:none!important}}</style></head>', 1)
                    header = ('<div style="width:100%;font-family:Arial,sans-serif;font-size:9px;line-height:1.3;'
                              'text-align:center;color:#b42318;background:#fff1e8;margin:0 14mm">'
                              + _e(DRAFT_WARNING) + '</div>')
                page.set_content(html, wait_until="load")
                content = page.pdf(format="A4", print_background=True, prefer_css_page_size=True, display_header_footer=True,
                                header_template=header, footer_template=FOOTER.format(title=_e(footer_title)),
                                margin={"top": "16mm", "bottom": "18mm", "left": "14mm", "right": "14mm"})
                if max_pages is not None:
                    import io
                    try:
                        from pypdf import PdfReader
                    except ImportError as exc:
                        raise PdfUnavailable("PDF page-count validation unavailable; no concise PDF returned") from exc
                    count = len(PdfReader(io.BytesIO(content)).pages)
                    if count > max_pages:
                        raise PdfPageLimit(f"Concise PDF has {count} pages; maximum {max_pages}. No incomplete PDF was returned. Use full technical/JSON/evidence downloads.")
                return content
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise PdfUnavailable(str(exc).splitlines()[0][:200]) from exc


_AVAILABLE: bool | None = None


def available() -> bool:
    """Whether a PDF can be made here. Tried once (a blank page), then remembered."""
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            to_pdf("<!doctype html><title>x</title>")
            _AVAILABLE = True
        except PdfUnavailable:
            _AVAILABLE = False
    return _AVAILABLE


class PdfPageLimit(PdfUnavailable):
    pass


def render_html(view, *, rows, plan, generated_at, demo=False, practical=None, concise=False, companions=None):
    if not concise:
        return render_full_html(view, rows=rows, plan=plan, generated_at=generated_at, demo=demo, practical=practical)
    from .concise_report import render
    return render(view, rows, generated_at, practical, companions or {}, demo=demo)
