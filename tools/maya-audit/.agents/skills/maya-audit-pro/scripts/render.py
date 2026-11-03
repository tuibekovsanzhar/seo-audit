"""data.json -> yatay HTML + PDF (Maya profesyonel denetim raporu): en çok 10 sayfa, 15 kart ve XLSX ek (DECISIONS 300).

Kullanım:
  python render.py data.json -o rapor.html --pdf rapor.pdf [--png KLASÖR]

PDF Playwright/Chromium ile basılır (1120×792 pt, 4 sayfa). Basmadan önce:
  - ⟪YAZ⟫ işareti kalmışsa durur (önce validate_data.py),
  - Maya Audit'in yayın kapısı çalışmazsa ya da engelleyici ihlal bulursa PDF basmaz (DECISIONS 278),
  - her alanın kutusuna sığıp sığmadığını tarayıcıda ölçer; taşan alanı adıyla yazar ve durur,
  - PDF'in tam 4 sayfa olduğunu ve Türkçe karakterlerin metinde korunduğunu denetler.
--png verilirse her sayfanın PNG önizlemesi yazılır (PyMuPDF gerekir).
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from inter_b64 import INTER_FACES  # noqa: E402

STEP_MARKER = re.compile(r"^\s*(?:[-•]|\d+[.)])\s+")
LABELS = json.loads((ROOT / "references" / "etiketler.json").read_text(encoding="utf-8"))
MARK = "⟪YAZ"


def e(s):
    return html.escape("" if s is None else str(s))


def font_css():
    out = []
    for weight, rng, b64 in INTER_FACES:
        out.append(f"@font-face{{font-family:'MayaInter';font-style:normal;font-weight:{weight};"
                   f"src:url(data:font/woff2;base64,{b64}) format('woff2');unicode-range:{rng};}}")
    return "\n".join(out)


CSS = """
@page { size: 1120pt 792pt; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
:root { --ink:#17212b; --muted:#596879; --faint:#738093; --line:#dfe4ea; --bg:#f8f9fb; --accent:#f15a24;
        --high:#b93840; --high-bg:#fceef0; --med:#97691d; --med-bg:#fbf5e7; --soft:#eff2f6; --na-bg:#fff4ed; --na-line:#f6d9cb; }
html, body { background: var(--bg); }
body { font-family: 'MayaInter', 'Segoe UI', system-ui, sans-serif; color: var(--ink); -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.page { width: 1120pt; height: 792pt; position: relative; overflow: hidden; background: var(--bg); page-break-after: always; break-after: page; }
.page:last-child { page-break-after: auto; break-after: auto; }
.top { background: #fff; height: 196pt; padding: 0 48pt; position: relative; }
.brandbar { height: 65pt; display: flex; align-items: center; justify-content: space-between; border-bottom: .6pt solid var(--line); }
.brandbar .left { display: flex; align-items: center; }
.brandbar img { height: 23pt; display: block; }
.brandbar .sep { width: .6pt; height: 24pt; background: var(--line); margin: 0 18pt 0 19pt; }
.kind { font-size: 8.4pt; font-weight: 600; color: var(--faint); letter-spacing: .3pt; }
.client { text-align: right; }
.client b { display: block; font-size: 10.5pt; font-weight: 600; }
.client span { font-size: 8.5pt; color: var(--faint); }
.headrow { display: flex; justify-content: space-between; align-items: flex-start; padding-top: 18pt; height: 86pt; }
.headrow h1 { font-size: 25pt; font-weight: 600; letter-spacing: -.2pt; line-height: 1.2; }
.headrow p { font-size: 10.2pt; color: var(--muted); margin-top: 6pt; }
.meta { text-align: right; }
.pill { display: inline-block; font-size: 9pt; padding: 5pt 9pt; border-radius: 3pt; }
.pill.covpill { background: var(--med-bg); color: var(--med); }
.pill.covpill.ok { background: var(--soft); color: var(--muted); }
.meta .date { font-size: 9.2pt; color: var(--faint); margin-top: 14pt; }
.tabs { display: flex; height: 45pt; align-items: center; border-bottom: .6pt solid var(--line); position: absolute; left: 48pt; right: 48pt; bottom: 0; }
.tab { font-size: 10.5pt; color: var(--muted); height: 45pt; display: flex; align-items: center; position: relative; }
.tab:nth-child(1) { width: 150pt; } .tab:nth-child(2) { width: 185pt; } .tab:nth-child(3) { width: 205pt; } .tab:nth-child(4) { width: 165pt; }
.tab.on { color: var(--ink); font-weight: 600; }
.tab.on::after { content: ''; position: absolute; left: 0; right: 22pt; bottom: -1pt; height: 2.5pt; background: var(--accent); }
.body { padding: 22pt 48pt 0; height: 562pt; }
.card { background: #fff; border: .6pt solid var(--line); border-radius: 5pt; }
.foot { position: absolute; left: 48pt; right: 48pt; bottom: 0; height: 34pt; border-top: .6pt solid var(--line);
        display: flex; justify-content: space-between; align-items: center; font-size: 7.8pt; color: var(--faint); }
.mono { font-family: Consolas, 'Cascadia Mono', Menlo, monospace; }
.clip { overflow: hidden; }
/* sayfa 1 */
.kpis { display: flex; height: 112pt; padding: 20pt 0; }
.kpi { flex: 1; padding: 0 20pt; border-left: .6pt solid var(--line); }
.kpi:first-child { border-left: 0; }
.kpi .l { font-size: 10pt; font-weight: 600; }
.kpi .v { font-size: 34pt; font-weight: 400; line-height: 1.25; margin-top: 4pt; letter-spacing: -.5pt; }
.kpi .v small { font-size: 13pt; color: var(--faint); margin-left: 6pt; letter-spacing: 0; }
.kpi .v.na { font-size: 20pt; color: var(--faint); line-height: 2.1; }
.kpi .s { font-size: 8.4pt; color: var(--muted); margin-top: 2pt; white-space: nowrap; overflow: hidden; text-overflow: clip; }
.assess { margin-top: 20pt; height: 94pt; position: relative; padding: 16pt 20pt 0 21pt; overflow: hidden; }
.assess::before { content: ''; position: absolute; left: -.6pt; top: -.6pt; bottom: -.6pt; width: 3pt; background: var(--accent); border-radius: 3pt 0 0 3pt; }
.eyebrow { font-size: 8.4pt; font-weight: 600; color: var(--faint); letter-spacing: .3pt; }
.assess h2 { font-size: 17pt; font-weight: 600; margin-top: 8pt; line-height: 1.25; }
.assess p { font-size: 10.1pt; color: var(--muted); margin-top: 7pt; line-height: 1.4; }
.row2 { display: flex; gap: 20pt; margin-top: 20pt; height: 274pt; }
.prio { flex: 0 0 668pt; padding: 18pt 20pt; }
.cardhead { display: flex; justify-content: space-between; align-items: baseline; }
.cardhead h3 { font-size: 12pt; font-weight: 600; }
.cardhead span { font-size: 9pt; color: var(--faint); }
.pitem { display: flex; padding: 12pt 0 10pt; border-top: .6pt solid var(--line); margin-left: 33pt; position: relative; height: 68pt; }
.cardhead + .pitem { border-top: 0; margin-top: 8pt; }
.pitem .n { position: absolute; left: -33pt; top: 13pt; font-size: 10pt; font-weight: 600; color: var(--accent); }
.pitem .tx { flex: 1; overflow: hidden; }
.pitem .tx b { font-size: 11.6pt; font-weight: 600; line-height: 1.2; display: block; white-space: nowrap; overflow: hidden; }
.pitem .tx p { font-size: 9.8pt; color: var(--muted); margin-top: 4pt; line-height: 1.35; max-height: 27pt; overflow: hidden; }
.pitem .val { font-size: 11.6pt; font-weight: 600; white-space: nowrap; padding-left: 14pt; }
.tone-high { color: var(--high); } .tone-medium { color: var(--med); } .tone-low { color: var(--muted); } .tone-accent { color: var(--accent); }
.cov { flex: 1; padding: 18pt 20pt; position: relative; }
.cov .badge { display: inline-block; background: var(--soft); color: var(--muted); font-size: 9pt; padding: 5pt 9pt; border-radius: 3pt; margin-top: 16pt; }
.covrow { display: flex; justify-content: space-between; font-size: 10pt; color: var(--muted); padding: 10pt 0; border-top: .6pt solid var(--line); }
.badge + .covrow { border-top: 0; margin-top: 10pt; }
.covrow b { font-size: 11pt; color: var(--ink); font-weight: 600; }
.cov .note { position: absolute; left: 20pt; right: 20pt; bottom: 18pt; font-size: 9pt; color: var(--faint); }
/* sayfa 2 */
.ftable { padding: 16pt 20pt 6pt; height: 314pt; }
table { width: 100%; border-collapse: collapse; }
th { text-align: left; font-size: 9pt; font-weight: 600; color: var(--faint); padding: 0 0 12pt; border-bottom: .6pt solid var(--line); }
.ftable td { padding: 7pt 0; border-bottom: .6pt solid var(--line); vertical-align: middle; height: 49pt; }
.ftable tr:last-child td { border-bottom: 0; }
.ftable .t { font-size: 11pt; font-weight: 600; max-width: 520pt; white-space: nowrap; overflow: hidden; }
.ftable .id { font-size: 8.3pt; color: var(--faint); margin-top: 5pt; }
.ftable .sc { font-size: 10.2pt; }
.ftable .st { font-size: 9.2pt; color: var(--muted); }
.sev { display: inline-block; font-size: 9pt; padding: 5pt 8pt; border-radius: 3pt; }
.sev.S1, .sev.S2 { background: var(--high-bg); color: var(--high); }
.sev.S3 { background: var(--med-bg); color: var(--med); }
.sev.S4, .sev.Info { background: var(--soft); color: var(--muted); }
.row2b { display: flex; gap: 20pt; margin-top: 20pt; height: 206pt; }
.sample { flex: 0 0 668pt; padding: 18pt 20pt; position: relative; }
.sample .cap { font-size: 9pt; color: var(--faint); margin-top: 8pt; }
.sample table { margin-top: 16pt; }
.sample th { font-size: 8.4pt; padding-bottom: 9pt; }
.sample td { font-size: 10.5pt; padding: 9pt 0 4pt; white-space: nowrap; overflow: hidden; max-width: 330pt; }
.sample td.alert { color: var(--high); font-weight: 600; }
.sample .note { position: absolute; left: 20pt; bottom: 16pt; font-size: 8.6pt; color: var(--faint); }
.next { flex: 1; background: var(--na-bg); border: .6pt solid var(--na-line); border-radius: 5pt; padding: 18pt 20pt; position: relative; }
.next .eyebrow { color: var(--accent); }
.next .lead { font-size: 11pt; line-height: 1.45; margin-top: 12pt; max-height: 80pt; overflow: hidden; }
.next .lead b { font-weight: 600; }
.next .cav { position: absolute; left: 20pt; right: 20pt; bottom: 16pt; border-top: .6pt solid var(--na-line); padding-top: 14pt;
             font-size: 9pt; color: var(--muted); line-height: 1.4; max-height: 56pt; overflow: hidden; }
/* sayfa 3 */
.row3 { display: flex; gap: 20pt; height: 290pt; }
.search { flex: 0 0 668pt; padding: 18pt 20pt; position: relative; }
.search .sub { font-size: 9pt; color: var(--faint); margin-top: 7pt; }
.search table { margin-top: 18pt; }
.search th { font-size: 8.4pt; padding-bottom: 9pt; }
.search td { padding: 10pt 0 8pt; border-bottom: .6pt solid var(--line); vertical-align: top; height: 55pt; }
.search tr:last-child td { border-bottom: 0; }
.search .q { font-size: 11.6pt; font-weight: 600; max-width: 300pt; white-space: nowrap; overflow: hidden; }
.search .ql { font-size: 9pt; color: var(--faint); margin-top: 7pt; }
.search .vol { font-size: 11pt; font-weight: 600; text-align: right; }
.bar { height: 3pt; background: var(--soft); border-radius: 2pt; margin-top: 9pt; position: relative; }
.bar i { position: absolute; left: 0; top: 0; bottom: 0; background: var(--accent); border-radius: 2pt; }
.rank { display: inline-block; min-width: 22pt; padding: 5pt 7pt; background: var(--soft); border-radius: 3pt; font-size: 9pt; text-align: center; }
.search .src { position: absolute; left: 20pt; bottom: 16pt; font-size: 8.6pt; color: var(--faint); }
.empty { font-size: 10.5pt; color: var(--muted); margin-top: 30pt; line-height: 1.5; }
.lab { flex: 1; padding: 18pt 20pt; position: relative; }
.lab .sub { font-size: 9pt; color: var(--faint); margin-top: 9pt; }
.big { font-size: 53pt; font-weight: 400; line-height: 1.1; margin-top: 12pt; letter-spacing: -1pt; }
.big small { font-size: 16pt; color: var(--muted); margin-left: 18pt; letter-spacing: 0; }
.gauge { height: 6pt; background: var(--soft); border-radius: 3pt; margin-top: 14pt; position: relative; }
.gauge i { position: absolute; left: 0; top: 0; bottom: 0; background: var(--accent); border-radius: 3pt; }
.ticks { display: flex; justify-content: space-between; font-size: 8pt; color: var(--faint); margin-top: 8pt; padding-bottom: 12pt; border-bottom: .6pt solid var(--line); }
.diag { margin-top: 14pt; }
.diag div { font-size: 10.4pt; font-weight: 600; margin-top: 9pt; display: flex; justify-content: space-between; }
.diag div span { font-weight: 400; color: var(--muted); }
.lab .src { position: absolute; left: 20pt; bottom: 16pt; font-size: 8.6pt; color: var(--faint); }
.row3b { display: flex; gap: 20pt; margin-top: 20pt; height: 230pt; }
.comm { flex: 0 0 668pt; padding: 18pt 20pt; position: relative; }
.comm p, .limits p { font-size: 11pt; color: var(--muted); line-height: 1.45; margin-top: 14pt; }
.comm .rp { position: absolute; left: 20pt; right: 20pt; bottom: 18pt; border-top: .6pt solid var(--line); padding-top: 16pt; }
.comm .rp div { font-size: 10.5pt; margin-top: 9pt; white-space: nowrap; overflow: hidden; }
.limits { flex: 1; padding: 18pt 20pt; position: relative; }
.limits .act { position: absolute; left: 20pt; right: 20pt; bottom: 18pt; border-top: .6pt solid var(--line); padding-top: 16pt; font-size: 10pt; line-height: 1.4; }
.field { margin-top: 12pt; font-size: 9.5pt; color: var(--muted); }
.field b { color: var(--ink); font-weight: 600; }
/* sayfa 4 */
.acts { padding: 18pt 20pt 8pt; height: 330pt; }
.acts table { margin-top: 16pt; }
.acts th { font-size: 8.4pt; padding-bottom: 9pt; }
.acts td { padding: 10pt 0 7pt; border-bottom: .6pt solid var(--line); vertical-align: top; height: 51pt; }
.acts tr:last-child td { border-bottom: 0; }
.acts .no { width: 44pt; font-size: 10pt; font-weight: 600; color: var(--accent); padding-top: 12pt; }
.acts .t { font-size: 11pt; font-weight: 600; max-width: 640pt; white-space: nowrap; overflow: hidden; }
.acts .id { font-size: 8.1pt; color: var(--faint); margin-top: 6pt; }
.acts .o, .acts .ef { font-size: 10.2pt; padding-top: 14pt; }
.acts .ef { color: var(--muted); }
.row4 { display: flex; gap: 20pt; margin-top: 20pt; height: 190pt; }
.row4 .card { flex: 1; padding: 18pt 20pt; position: relative; }
.row4 .eyebrow { margin-top: 9pt; }
.row4 p { font-size: 11pt; color: var(--muted); line-height: 1.45; margin-top: 16pt; max-height: 64pt; overflow: hidden; }
.row4 .fn { position: absolute; left: 20pt; bottom: 18pt; font-size: 8.7pt; color: var(--faint); }
.later .lr { display: flex; align-items: baseline; margin-top: 13pt; }
.later .eyebrow + .lr { margin-top: 18pt; }
.later b { font-size: 13pt; font-weight: 600; width: 32pt; }
.later span { font-size: 8.8pt; color: var(--muted); white-space: nowrap; overflow: hidden; max-width: 230pt; }
.prov p { font-size: 9.5pt; line-height: 1.45; margin-top: 12pt; }
/* yapılacaklar sayfaları */
.todos { display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; gap: 20pt; height: 540pt; }
.todo { padding: 16pt 20pt 14pt; position: relative; overflow: hidden; }
.todo .th { display: flex; align-items: flex-start; }
.todo .box { flex: 0 0 11pt; height: 11pt; border: 1.2pt solid var(--faint); border-radius: 2pt; margin: 2pt 10pt 0 0; }
.todo .tn { font-size: 10pt; font-weight: 600; color: var(--accent); margin-right: 9pt; padding-top: 1pt; }
.todo .th b { font-size: 11pt; font-weight: 600; line-height: 1.3; max-height: 29pt; overflow: hidden; flex: 1; }
.todo .tm { font-size: 8.6pt; color: var(--muted); margin-top: 6pt; padding-left: 41pt; white-space: nowrap; overflow: hidden; }
.todo .tm .sev { font-size: 8pt; padding: 3pt 6pt; margin-right: 4pt; }
.todo .tm .mono { color: var(--faint); font-size: 8pt; }
.todo-status {font-size:8.3pt;color:var(--muted);margin:2pt 0 0 41pt;line-height:1.2;}
.todo-fact {font-size:8.3pt;color:var(--ink);margin:2pt 0 0 41pt;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.todo-fact b {color:var(--muted);font-weight:600;}
.todo-sub {font-size:8.1pt;color:var(--ink);margin:2pt 0 0 41pt;line-height:1.25;}
.todo-sub div {white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.todo-sub div::before {content:'• ';color:var(--faint);}
.todo.sub ol { height: auto; max-height: 60pt; }
.todo .sec { margin-top: 6pt; padding-left: 41pt; }
.todo .sec .eyebrow { font-size: 7.6pt; }
.todo ol { margin: 5pt 0 0 0; padding-left: 15pt; font-size: 9.2pt; color: var(--ink); line-height: 1.32; height: 60pt; overflow: hidden; }
.todo ol li { margin-top: 2pt; }
.todo .vf { font-size: 9pt; color: var(--muted); line-height: 1.35; margin-top: 4pt; max-height: 25pt; overflow: hidden; }
.todo .links { display: grid; grid-template-columns: 1fr 1fr; column-gap: 14pt; row-gap: 2pt; margin-top: 4pt; }
.todo .links a { font-size: 8.4pt; color: #2f5d8a; text-decoration: none; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.todo .links a::before { content: '↗ '; color: var(--faint); }
.todo .more { font-size: 8pt; color: var(--faint); margin-top: 4pt; }
.todo .sw { font-size: 9pt; color: var(--muted); margin-top: 4pt; }
.todo table.lk { width: 100%; border-collapse: collapse; table-layout: fixed; margin-top: 3pt; font-size: 7.6pt; }
.todo table.lk th:nth-child(1) { width: 25%; } .todo table.lk th:nth-child(2) { width: 18%; }
.todo table.lk th:nth-child(3) { width: 22%; } .todo table.lk th:nth-child(4) { width: 21%; }
.todo table.lk th { text-align: left; text-overflow: ellipsis; color: var(--faint); font-weight: 600; padding: 0 4pt 2pt 0; white-space: nowrap; overflow: hidden; }
.todo table.lk td { padding: 2pt 4pt 1pt 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-top: 0.5pt solid var(--line); }
.todo .lknote { font-size: 7.6pt; color: var(--faint); margin-top: 3pt; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.rp .eyebrow, .diag .eyebrow { font-size: 8.4pt !important; font-weight: 600 !important; color: var(--faint) !important; display: block !important; margin-top: 0 !important; }
.prov p b { font-weight: 600; color: var(--muted); }
/* DECISIONS 300: the last page (coverage, confirm first, key pages, appendix) */
.p6 { display: grid; grid-template-columns: 1fr 1fr; gap: 18pt; height: 540pt; }
.p6 .card { padding: 14pt 18pt; overflow: hidden; }
.p6 .card h3 { font-size: 11.5pt; }
.p6 ul { margin: 7pt 0 0 0; padding-left: 13pt; font-size: 8.8pt; line-height: 1.32; color: var(--ink); }
.p6 li { margin-top: 3pt; }
.p6 .why { color: var(--muted); }
.p6 .note { font-size: 8.4pt; color: var(--faint); margin-top: 6pt; line-height: 1.3; }
.p6 table { width: 100%; border-collapse: collapse; table-layout: fixed; margin-top: 7pt; font-size: 8.4pt; }
.p6 th { text-align: left; color: var(--faint); font-weight: 600; padding: 0 4pt 3pt 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.p6 td { padding: 3pt 4pt 2pt 0; border-top: .5pt solid var(--line); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.p6 th:nth-child(1) { width: 6%; } .p6 th:nth-child(2) { width: 31%; } .p6 th:nth-child(3) { width: 11%; }
.p6 th:nth-child(4) { width: 14%; } .p6 th:nth-child(5) { width: 14%; } .p6 th:nth-child(6) { width: 11%; }
.p6 .left, .p6 .right { display: flex; flex-direction: column; gap: 18pt; }
.p6 .app p { font-size: 9.6pt; line-height: 1.4; margin-top: 7pt; }
.quick .q { font-size: 9.2pt; color: var(--ink); margin-top: 9pt; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.quick .q b { color: var(--accent); margin-right: 6pt; }
"""


def has_search_or_performance(d):
    """DECISIONS 283 (5): the "search and performance" page is printed only when it has something to show: search
    data, a lab result or field data. Without any, page 1's KPI already says "not measured"."""
    if "search" not in d:
        return True  # data.json from before the search box existed: the page as it always was
    return (d.get("search") or {}).get("state") not in (None, "missing") or bool(d.get("lab")) or bool(d.get("field"))


def has_client_page(d):
    """DECISIONS 300: data.json from a selection has the last page (coverage, confirm first, key pages, appendix)."""
    return "appendix" in d


def summary_pages(d):
    """The summary pages' tab indexes (0..3); 2 is "search and performance"."""
    return [0, 1, 2, 3] if has_search_or_performance(d) else [0, 1, 3]


def header(d, L, idx, title, sub):
    m = d["meta"]
    logo = base64.b64encode((ROOT / "assets" / "maya_logo.png").read_bytes()).decode()
    shown = summary_pages(d) + [4] + ([5] if has_client_page(d) else [])
    tabs = "".join(f'<div class="tab{" on" if i == idx else ""}">{e(L["tabs"][i])}</div>' for i in shown)
    date = e(m["date"]) + (f" &nbsp;/&nbsp; {e(m['revision'])}" if m.get("revision") else "")
    ok = " ok" if m["coverage_level"] == "complete_sample" else ""
    return f"""
<div class="top">
  <div class="brandbar">
    <div class="left"><img src="data:image/png;base64,{logo}" alt="maya"><div class="sep"></div><span class="kind">{e(L['doc_kind'])}</span></div>
    <div class="client"><b data-slot="meta.brand" class="clip">{e(m['brand'])}</b><span>{e(m['domain'])}</span></div>
  </div>
  <div class="headrow">
    <div><h1>{e(title)}</h1><p>{e(sub)}</p></div>
    <div class="meta"><span class="pill covpill{ok}">{e(m['coverage_label'])}</span><div class="date">{date}</div></div>
  </div>
  <div class="tabs">{tabs}</div>
</div>"""


def footer(d, L, n, total=4):
    m = d["meta"]
    left = (L["footer_left_src"].format(source=m["source"], audit_id=m["audit_id"]) if m.get("source")
            else L["footer_left"].format(audit_id=m["audit_id"]))
    right = L["footer_right"].format(version=m["engine_version"], date=m["date"])
    return f'<div class="foot"><span>{e(left)}</span><span>{e(right)} &nbsp;&nbsp; {n:02d} / {total:02d}</span></div>'


def page1(d, L):
    kp = []
    for i, k in enumerate(d["kpis"]):
        if k["state"] == "missing":
            v = f'<div class="v na">{e(k["value"])}</div>'
        else:
            v = f'<div class="v">{e(k["value"])}' + (f'<small>/ {e(k["of"])}</small>' if k.get("of") else "") + "</div>"
        kp.append(f'<div class="kpi"><div class="l">{e(k["label"])}</div>{v}<div class="s" data-slot="kpis[{i}].sub">{e(k["sub"])}</div></div>')
    pr = []
    for i, p in enumerate(d["priorities"]):
        pr.append(f'<div class="pitem"><span class="n">{p["n"]:02d}</span><div class="tx">'
                  f'<b data-slot="priorities[{i}].title">{e(p["title"])}</b><p data-slot="priorities[{i}].text">{e(p["text"])}</p></div>'
                  f'<div class="val tone-{p["tone"]}">{e(p["value"])}</div></div>')
    cov = d["coverage"]
    rows = "".join(f'<div class="covrow"><span>{e(r["label"])}</span><b>{e(r["value"])}</b></div>' for r in cov["rows"])
    return f"""
<div class="body">
  <div class="card kpis">{''.join(kp)}</div>
  <div class="card assess"><div class="eyebrow">{e(L['assessment'])}</div>
    <h2 data-slot="assessment.headline">{e(d['assessment']['headline'])}</h2><p data-slot="assessment.text">{e(d['assessment']['text'])}</p></div>
  <div class="row2">
    <div class="card prio"><div class="cardhead"><h3>{e(L['priorities'])}</h3><span>{e(L['priorities_n'].format(n=len(d['priorities'])))}</span></div>{''.join(pr)}</div>
    <div class="card cov"><div class="cardhead"><h3>{e(L['evidence_coverage'])}</h3></div><span class="badge">{e(cov['badge'])}</span>{rows}
      <div class="note">{e(cov['note'])}</div></div>
  </div>
</div>"""


def page2(d, L):
    trs = []
    for i, f in enumerate(d["findings"]):
        trs.append(f'<tr><td><div class="t" data-slot="findings[{i}].title">{e(f["title"])}</div><div class="id mono">{e(f["id"])}</div></td>'
                   f'<td class="sc">{e(f["scope"])}</td><td><span class="sev {e(f["severity"])}">{e(f["severity_label"])}</span></td>'
                   f'<td class="st">{e(f["status"])}</td></tr>')
    ftable = (f'<div class="card ftable"><table><colgroup><col style="width:56%"><col style="width:11%"><col style="width:11%"><col></colgroup>'
              f'<tr><th>{e(L["col_finding"])}</th><th>{e(L["col_scope"])}</th><th>{e(L["col_severity"])}</th><th>{e(L["col_status"])}</th></tr>'
              f'{"".join(trs)}</table></div>')
    s = d.get("evidence_sample")
    if s:
        head = "".join(f"<th>{e(c)}</th>" for c in s["columns"])
        body = ""
        for r in s["rows"]:
            cells = []
            for j, c in enumerate(r):
                cls = ' class="alert"' if s.get("alert_col") == j else (' class="mono"' if j in (1, 2) and s["kind"] == "attempts" else "")
                cells.append(f"<td{cls}>{e(c)}</td>")
            body += "<tr>" + "".join(cells) + "</tr>"
        sample = (f'<div class="card sample"><div class="cardhead"><h3>{e(L["evidence_sample"])}</h3></div>'
                  f'<div class="cap">{e(s["caption"])}</div><table><tr>{head}</tr>{body}</table><div class="note">{e(s["note"])}</div></div>')
    else:
        sample = f'<div class="card sample"><div class="cardhead"><h3>{e(L["evidence_sample"])}</h3></div><div class="empty">—</div></div>'
    na = d["next_action"]
    nxt = (f'<div class="next"><div class="eyebrow">{e(L["next_action"])}</div>'
           f'<div class="lead" data-slot="next_action.text"><b data-slot="next_action.lead">{e(na["lead"])}</b> {e(na["text"])}</div>'
           f'<div class="cav" data-slot="next_action.caveat">{e(na["caveat"])}</div></div>')
    return f'<div class="body">{ftable}<div class="row2b">{sample}{nxt}</div></div>'


def page3(d, L):
    s = d["search"]
    if s["state"] == "ok":
        rows = ""
        for r in s["rows"]:
            w = max(2, round(r["share"] * 100))
            rows += (f'<tr><td><div class="q">{e(r["query"])}</div><div class="ql">{e(r["label"])}</div></td>'
                     f'<td><div class="vol">{e(r["volume"])}</div><div class="bar"><i style="width:{w}%"></i></div></td>'
                     f'<td style="text-align:center"><span class="rank">{e(r["rank"])}</span></td></tr>')
        inner = (f'<div class="sub">{e(L["search_sub"])}</div><table><colgroup><col style="width:52%"><col style="width:33%"><col></colgroup>'
                 f'<tr><th>{e(L["col_query"])}</th><th style="text-align:right">{e(L["col_volume"])}</th><th style="text-align:center">{e(L["col_rank"])}</th></tr>'
                 f'{rows}</table><div class="src">{e(s["source"])}</div>')
    else:
        inner = f'<div class="empty">{e(s["note"])}</div>'
    search = f'<div class="card search"><div class="cardhead"><h3>{e(L["search_visibility"])}</h3></div>{inner}</div>'
    lab = d.get("lab")
    if lab and lab.get("score") is not None:
        diags = "".join(f'<div><span style="color:var(--ink);font-weight:600">{e(x["label"])}</span><span>{e(x["value"] or "")}</span></div>'
                        for x in lab["diagnostics"]) or f'<div style="font-weight:400;color:var(--muted)">{e(L["lab_diag_none"])}</div>'
        labc = (f'<div class="card lab"><div class="cardhead"><h3>{e(L["lab_title"])}</h3></div><div class="sub">{e(L["lab_sub"].format(date=lab["date"]))}</div>'
                f'<div class="big">{e(lab["score"])}<small>/ 100</small></div><div class="gauge"><i style="width:{max(1, min(100, int(lab["score"])))}%"></i></div>'
                f'<div class="ticks"><span>0</span><span>50</span><span>100</span></div>'
                f'<div class="diag"><div class="eyebrow" style="display:block">{e(L["lab_diag"])}</div>{diags}</div>'
                f'<div class="src">{e(L["lab_source"])}</div></div>')
    else:
        labc = (f'<div class="card lab"><div class="cardhead"><h3>{e(L["lab_title"])}</h3></div>'
                f'<div class="big" style="font-size:22pt;color:var(--faint)">{e(L["not_measured"])}</div><div class="empty">{e(L["lab_none"])}</div></div>')
    rp = s.get("ranking_page") if s["state"] == "ok" else None
    comm = (f'<div class="card comm"><div class="cardhead"><h3>{e(L["commercial"])}</h3></div><p data-slot="commercial">{e(d["commercial"])}</p>'
            + (f'<div class="rp"><div class="eyebrow">{e(L["ranking_page"])}</div><div class="mono">{e(rp)}</div></div>' if rp else "") + "</div>")
    field = d.get("field")
    fhtml = ""
    if not field:
        fhtml = f'<div class="field"><b>{e(L["field_title"])}</b>: {e(L["not_measured"])}</div>'
    if field:
        vals = " · ".join(f'{e(r["label"])} {e(r["value"])}' for r in field["rows"])
        fhtml = f'<div class="field"><b>{e(L["field_pass"] if field["pass"] else L["field_fail"])}</b> · {vals}</div>'
    lim = d["limits"]
    limits = (f'<div class="card limits"><div class="cardhead"><h3>{e(L["limits"])}</h3></div><p data-slot="limits.text">{e(lim["text"])}</p>{fhtml}'
              f'<div class="act" data-slot="limits.action">{e(lim["action"])}</div></div>')
    return f'<div class="body"><div class="row3">{search}{labc}</div><div class="row3b">{comm}{limits}</div></div>'


def page4(d, L):
    trs = ""
    for i, a in enumerate(d["actions"]):
        trs += (f'<tr><td class="no">{a["n"]:02d}</td><td><div class="t" data-slot="actions[{i}].title">{e(a["title"])}</div>'
                f'<div class="id mono">{e(a["ref"])}</div></td><td class="o">{e(a["owner"])}</td><td class="ef">{e(a["effort"])}</td></tr>')
    acts = (f'<div class="card acts"><div class="cardhead"><h3>{e(L["priority_actions"])}</h3><span>{e(d["actions_schedule"])}</span></div>'
            f'<table><colgroup><col style="width:44pt"><col><col style="width:150pt"><col style="width:110pt"></colgroup>'
            f'<tr><th>{e(L["col_no"])}</th><th>{e(L["col_action"])}</th><th>{e(L["col_owner"])}</th><th>{e(L["col_effort"])}</th></tr>{trs}</table></div>')
    fu = d["followup"]
    follow = (f'<div class="card"><div class="cardhead"><h3>{e(L["followup"])}</h3></div>'
              f'<div class="eyebrow">{e(L["schedule_caps"].format(when=L["when"]["month"].upper()))}</div>'
              f'<p data-slot="followup.text">{e(fu["text"])}</p><div class="fn">{e(fu["note"])}</div></div>')
    later = "".join(f'<div class="lr"><b>{e(x["count"])}</b><span data-slot="later[{i}].label">{e(x["label"])}</span></div>' for i, x in enumerate(d["later"])) or '<div class="lr"><span>—</span></div>'
    sub = (f'<div class="card later"><div class="cardhead"><h3>{e(L["subsequent"])}</h3></div>'
           f'<div class="eyebrow">{e(L["schedule_caps"].format(when=L["when"]["later"].upper()))}</div>{later}</div>')
    if has_client_page(d):
        # DECISIONS 300: the action plan carries the quick wins (cards with a small effort) in place of "later".
        todos = {t["n"]: t for t in d.get("todos") or []}
        rows = "".join(f'<div class="q"><b>{n:02d}</b>{e(todos[n]["title"])}</div>' for n in d.get("quick_wins") or [] if n in todos)
        sub = (f'<div class="card quick"><div class="cardhead"><h3>{e(L["quick_title"])}</h3></div>'
               + (rows or f'<div class="q">{e(L["quick_none"])}</div>') + '</div>')
    pv = d["provenance"]
    lines = "".join(f'<p><b>{e(x["k"])}</b> {e(x["v"])}</p>' for x in pv["lines"])
    prov = f'<div class="card prov"><div class="cardhead"><h3>{e(L["provenance"])}</h3></div>{lines}<div class="fn">{e(pv["note"])}</div></div>'
    if not d["actions"]:
        acts = ""  # DECISIONS 287: no empty "priority actions" table (a report that read nothing has none)
    return f'<div class="body">{acts}<div class="row4">{follow}{sub}{prov}</div></div>'


def target_line(urls, shown=2):
    """The failing addresses of a broken-link card, as paths: the first two and how many more."""
    from urllib.parse import urlsplit
    paths = [((urlsplit(u).path or "/") + (("?" + urlsplit(u).query) if urlsplit(u).query else "")) for u in urls]
    return " · ".join(paths[:shown]) + (f" · +{len(paths) - shown}" if len(paths) > shown else "")


LINK_ROWS = 2  # rows of the "links to edit" table a card has room for; the rest are in the address list


def link_table(rows, L):
    """DECISIONS 283: a broken link's card shows where to edit it, one row per link (page to edit, link text, the
    address it links to, where it ends, replacement), as the web PDF does. The replacement is always unknown."""
    head = "".join(f"<th>{e(c)}</th>" for c in L["link_cols"])
    body = []
    for r in rows[:LINK_ROWS]:
        source = path_or_host(r["source_url"])
        if r.get("kind") == "sitemap":
            source = f'{L["link_sitemap"]}: {source}'
        ends = path_or_host(r["target_url"]) if r.get("target_url") else "—"
        if r.get("target_url") and r.get("target_status"):
            ends += f' ({r["target_status"]})'
        cells = (source, r.get("link_text") or "—", path_or_host(r.get("links_to")), ends,
                 path_or_host(r["replacement_url"]) if r.get("replacement_url") else L["link_unknown"])
        body.append("<tr>" + "".join(f"<td>{e(c)}</td>" for c in cells) + "</tr>")
    more = len(rows) - LINK_ROWS
    return (f'<table class="lk"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'
            + (f'<div class="more">{e(L["link_more"].format(n=more))}</div>' if more > 0 else "")
            + f'<div class="lknote">{e(L["link_note"])}</div>')


def path_or_host(url):
    from urllib.parse import urlsplit
    if not url:
        return "—"
    p = urlsplit(url)
    path = (p.path or "/") + (("?" + p.query) if p.query else "")
    return path if path != "/" else (p.netloc or url)


SUB_LINES = 5  # lines under a card's status (the overflow check measures them); more are counted


def sub_lines(t, L):
    lines = list(t.get("sub") or [])
    shown = lines[:SUB_LINES] if len(lines) <= SUB_LINES else lines[:SUB_LINES - 1]
    rest = len(lines) - len(shown)
    body = "".join(f"<div>{e(x)}</div>" for x in shown)
    if rest:
        body += f"<div>{e(L['sub_more'].format(n=rest))}</div>"
    return f'<div class="todo-sub">{body}</div>'


def todo_pages(d, L):
    """Yapılacaklar: sayfa başına 4 kart (2×2). Her kart: onay kutusu, iş, takvim/sorumlu/efor, adımlar, doğrulama, linkler."""
    todos = d.get("todos") or []
    pages = []
    for start in range(0, len(todos), 4):
        cards = []
        for t in todos[start:start + 4]:
            i = t["n"] - 1
            # Strip a list marker ("- ", "• ", "1. ", "2) ") only: lstrip of digits ate "404 ..." (Adile render).
            steps = "".join(f"<li>{e(STEP_MARKER.sub('', line).strip())}</li>" for line in str(t["steps"]).split("\n") if line.strip())
            if t["links"]:
                links = '<div class="links">' + "".join(f'<a href="{e(x["href"])}">{e(x["text"])}</a>' for x in t["links"]) + "</div>"
                links += f'<div class="more">{e(L["todo_more"].format(n=t["more"]))}</div>' if t["more"] else ""
            else:
                links = f'<div class="sw">{e(L["todo_sitewide"])}</div>'
            cards.append(
                f'<div class="card todo{" sub" if t.get("sub") else ""}"><div class="th"><span class="box"></span><span class="tn">{t["n"]:02d}</span>'
                f'<b data-slot="todos[{i}].title">{e(t["title"])}</b></div>'
                f'<div class="tm"><span class="sev {e(t["severity"])}">{e(t["severity_label"])}</span> {e(t["when"])} · {e(t["owner"])} · '
                f'{e(L["col_effort"].title() if d["lang"] == "en" else "Efor")}: {e(t["effort"])}'
                + (f' · {e(L["todo_priority"].format(score=t["priority"]))}' if t.get("priority") is not None else "")
                + f' · <span class="mono">{e(t["id"])}</span></div>'
                f'<div class="todo-status">{e(t["status"])}</div>'
                # DECISIONS 278: a broken link's failing address and the page to edit are two things, never swapped.
                # The target line takes the evidence line's place: that line mixes source and target ("/a · /b · 404"),
                # and a card has room for one such line (two overflowed the Carpex IDX-1 card, w13).
                # DECISIONS 284: a card for one cause found by several findings (or a sitemap card by reason) lists them
                # one per line where the single evidence line would be.
                + (sub_lines(t, L) if t.get("sub") else
                   "" if t.get("link_rows") else
                   f'<div class="todo-fact"><b>{e(L["todo_targets"])}:</b> {e(target_line(t["target_urls"]))}</div>'
                   if t.get("target_urls") else
                   f'<div class="todo-fact"><b>{e(L["todo_fact"])}:</b> {e(t["fact"])}</div>' if t.get("fact") else "")
                + ''
                f'<div class="sec"><div class="eyebrow">{e(L["todo_steps"])}</div><ol data-slot="todos[{i}].steps">{steps}</ol></div>'
                f'<div class="sec"><div class="eyebrow">{e(L["todo_verify"])}</div><div class="vf" data-slot="todos[{i}].verify">{e(t["verify"])}</div></div>'
                + (f'<div class="sec"><div class="eyebrow">{e(L["link_title"])}</div>{link_table(t["link_rows"], L)}</div></div>'
                   if t.get("link_rows") else
                   f'<div class="sec"><div class="eyebrow">{e(L["todo_sources"] if t.get("target_urls") else L["todo_links"])}</div>{links}</div></div>'))
        pages.append(f'<div class="body"><div class="todos">{"".join(cards)}</div></div>')
    return pages


def page6(d, L):
    """DECISIONS 300: Maya's own limits (never as the client's problems), "Teyit edin", key pages, the appendix."""
    own = "".join(f"<li>{e(x)}</li>" for x in d.get("own_limits") or []) or "<li>—</li>"
    limits = (f'<div class="card"><div class="cardhead"><h3>{e(L["own_title"])}</h3></div><ul>{own}</ul>'
              f'<div class="note">{e(L["own_note"])}</div></div>')
    rows = "".join(f'<li><span data-slot="confirm[{i}].title">{e(c["title"])}</span> · {e(c["severity_label"])} · {e(c["scope"])}'
                   f' <span class="why">· {e(c["reason"])}</span></li>' for i, c in enumerate(d.get("confirm") or []))
    if d.get("confirm_more"):
        rows += f'<li class="why">{e(L["confirm_more"].format(n=d["confirm_more"]))}</li>'
    confirm = (f'<div class="card"><div class="cardhead"><h3>{e(L["confirm_title"])}</h3></div>'
               f'<div class="note">{e(L["confirm_note"])}</div><ul>{rows or "<li>" + e(L["confirm_none"]) + "</li>"}</ul></div>')
    head = "".join(f"<th>{e(c)}</th>" for c in L["kp_cols"])
    body = "".join("<tr>" + "".join(f"<td>{e(v)}</td>" for v in (p["rank"], p["path"], p["type"], p["importance"], p["cards"],
                                                                  p["worst"], p["confirm"])) + "</tr>" for p in d.get("key_pages") or [])
    pages = (f'<div class="card"><div class="cardhead"><h3>{e(L["kp_title"])}</h3></div>'
             f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
    app = (f'<div class="card app"><div class="cardhead"><h3>{e(L["appendix_title"])}</h3></div>'
           f'<p>{e(d["appendix"]["line"])}</p></div>')
    return f'<div class="body"><div class="p6"><div class="left">{limits}{confirm}</div><div class="right">{pages}{app}</div></div></div>'


def build_html(d):
    L = LABELS[d["lang"]]
    nf = len(d["findings"])
    m = d["meta"]
    sub3 = L["p3_sub_market"].format(market=m["market"]) if m.get("market") else L["p3_sub_nomarket"]
    summary = {0: (L["p1_title"], L["p1_sub"], lambda: page1(d, L)),
               1: (L["p2_title"], L["p2_sub"].format(n=nf), lambda: page2(d, L)),
               2: (L["p3_title"], sub3, lambda: page3(d, L)),
               3: (L["p4_title"], L["p4_sub"], lambda: page4(d, L))}
    pages = [(tab, summary[tab][0], summary[tab][1], summary[tab][2]()) for tab in summary_pages(d)]
    for content in todo_pages(d, L):
        pages.append((4, L["p5_title"], L["p5_sub"], content))
    if has_client_page(d):
        pages.append((5, L["p6_title"], L["p6_sub"], page6(d, L)))
    total = len(pages)
    body = "".join(f'<section class="page">{header(d, L, tab, t, s)}{content}{footer(d, L, i + 1, total)}</section>'
                   for i, (tab, t, s, content) in enumerate(pages))
    title = f"Maya | {m['brand']} | {L['doc_kind'].title()}"
    return (f'<!doctype html><html lang="{d["lang"]}"><head><meta charset="utf-8"><title>{e(title)}</title>'
            f'<style>{font_css()}\n{CSS}</style></head><body>{body}</body></html>')


OVERFLOW_JS = """() => {
  const out = [];
  for (const el of document.querySelectorAll('[data-slot]')) {
    if (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1) out.push(el.dataset.slot);
  }
  // A slot can fit its own box and still be cut by a fixed-height box around it (a priority's second line, DECISIONS 275).
  for (const el of document.querySelectorAll('.pitem .tx, .todo')) {
    if (el.scrollHeight > el.clientHeight + 1) { const s = el.querySelector('[data-slot]'); out.push('kutu: ' + (s ? s.dataset.slot : el.className)); }
  }
  for (const el of document.querySelectorAll('.card, .next')) {
    if (el.scrollHeight > el.clientHeight + 1) { const lab = el.querySelector('h3') || el.querySelector('[data-slot]'); out.push('kart: ' + (lab ? (lab.dataset.slot || lab.textContent) : el.className)); }
  }
  for (const sec of document.querySelectorAll('section.page')) {
    const foot = sec.querySelector('.foot').getBoundingClientRect().top;
    sec.querySelectorAll('.body > *').forEach((el, i) => {
      if (el.getBoundingClientRect().bottom > foot + 0.5) out.push('sayfa ' + (Array.from(document.querySelectorAll('section.page')).indexOf(sec) + 1) + ': gövde alt bilgiye taşıyor');
    });
  }
  return out;
}"""


def render(html_path, pdf_path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1494, "height": 1056})
        page.route("**/*", lambda route: route.abort() if route.request.url.startswith(("http:", "https:", "ws:", "wss:")) else route.continue_())
        page.goto(html_path.resolve().as_uri())
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")
        over = page.evaluate(OVERFLOW_JS)
        if pdf_path:
            page.pdf(path=str(pdf_path), prefer_css_page_size=True, print_background=True)
        b.close()
    return over


def check_pdf(pdf_path, d):
    problems = []
    try:
        import fitz  # PyMuPDF
    except ImportError:
        from pypdf import PdfReader
        doc = PdfReader(pdf_path).pages
        texts = [pg.extract_text() or "" for pg in doc]
    else:
        doc = fitz.open(str(pdf_path))
        texts = [pg.get_text() for pg in doc]
    expected = len(summary_pages(d)) + -(-len(d.get("todos") or []) // 4) + (1 if has_client_page(d) else 0)
    if len(doc) != expected:
        problems.append(f"HATA: PDF {len(doc)} sayfa; {expected} olmalı (bir bölüm taştı)")
    # DECISIONS 300: the client PDF has at most 10 pages and 15 cards (release gate RG-15, RG-16).
    from validate_data import load_gate
    gate = load_gate(d)
    if gate is not None:
        for v in gate.check_client_output({}, pages=len(doc), cards=len(d.get("todos") or [])):
            problems.append(f"HATA: {v['rule']}: {v['message']}")
    elif len(doc) > 10 or len(d.get("todos") or []) > 15:
        problems.append("HATA: client PDF over 10 pages or 15 cards")
    text = "".join(texts)
    if d["lang"] == "tr" and not any(ch in text for ch in "ğüşıöçİĞÜŞÖÇ"):
        problems.append("HATA: PDF metninde Türkçe karakter yok; font gömülmemiş olabilir")
    if "⟪" in text:
        problems.append("HATA: PDF'te ⟪YAZ⟫ işareti var")
    return problems


def write_appendix(d, out):
    """DECISIONS 300 (4): the appendix, an XLSX with every finding and every affected address, from the same selection
    the cards came from (Maya Audit's client_selection, rebuilt from the report the gate reads). RG-17 is checked on
    the written file: every finding of the report must be in it. Returns (path, problems)."""
    from validate_data import load_gate
    if load_gate(d) is None or not d.get("_report_path"):
        return None, ["HATA: ek (XLSX) yazılamadı: Maya Audit motoru ya da report.json bulunamadı"]
    from maya_audit import client_appendix, client_selection, final  # type: ignore
    report = json.loads(Path(d["_report_path"]).read_text(encoding="utf-8"))
    affected = json.loads(Path(d["_affected_path"]).read_text(encoding="utf-8")) if d.get("_affected_path") else None
    sealed = final.from_report(report, affected)
    selection = client_selection.select(sealed.report, sealed.affected, d.get("_confirmations") or {})
    wording = {}
    try:
        from maya_audit_web import wording as w  # type: ignore
        wording = {"title": lambda cid, text: w.title(cid, text, d["lang"])[0], "fix": lambda text: w.fix(text, d["lang"])[0]}
    except Exception:
        pass
    content = client_appendix.build(selection, d["lang"], sealed.affected, **wording)
    path = out.with_name(out.stem + ("-appendix.xlsx" if d["lang"] == "en" else "-ek.xlsx"))
    path.write_bytes(content)
    from maya_audit import release_gate  # type: ignore
    problems = [f"HATA: {v['rule']}: {v['message']}" for v in
                release_gate.check_client_output(sealed.report, appendix_ids=client_appendix.finding_ids(content))]
    return path, problems


def write_address_list(d, out):
    """The "+N more" lines promise the attached address list; write it next to the HTML (Excel-friendly CSV).

    Returns None when no card has more addresses than it shows, so no promise is printed either. A broken-link card's
    rows carry the link text, where the link points, where it ends and the replacement (DECISIONS 283).
    """
    todos = d.get("todos") or []
    if not any(t.get("more") or len(t.get("link_rows") or []) > LINK_ROWS for t in todos):
        return None
    en = d["lang"] == "en"
    L = LABELS[d["lang"]]
    header = (["Card", "Finding", "Severity", "Address"] if en else ["Kart", "Bulgu", "Önem", "Adres"])
    if any(t.get("link_rows") for t in todos):
        header += L["link_cols"][1:]
    rows = []
    for t in todos:
        if t.get("link_rows"):
            for r in t["link_rows"]:
                source = r["source_url"] if r.get("kind") != "sitemap" else f'{L["link_sitemap"]}: {r["source_url"]}'
                ends = (f'{r["target_url"]} ({r["target_status"]})' if r.get("target_status") else r.get("target_url")) or ""
                rows.append([t["n"], t["id"], t["severity_label"], source, r.get("link_text") or "", r.get("links_to") or "",
                             ends, r.get("replacement_url") or L["link_unknown"]])
            continue
        for u in t.get("all_urls") or [l["href"] for l in t.get("links") or []]:
            rows.append([t["n"], (t.get("url_finding") or {}).get(u, t["id"]), t["severity_label"], u])
        if t.get("unlisted"):
            note = (f"{t['unlisted']} more addresses were not listed in the audit data" if en
                    else f"{t['unlisted']} adres denetim verisinde listelenmedi")
            rows.append([t["n"], t["id"], t["severity_label"], note])
    import csv
    path = out.with_name(out.stem + ("-addresses.csv" if en else "-adresler.csv"))
    # UTF-8 with a byte-order mark so Excel reads Turkish letters; ";" for Turkish, whose Excel takes "," as the decimal
    # mark and would put a whole row in one cell (DECISIONS 283 (6)).
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        csv.writer(fh, delimiter="," if en else ";").writerows([header] + rows)
    return path


def write_previews(pdf, folder):
    folder.mkdir(parents=True, exist_ok=True)
    try:
        import fitz
    except ImportError:
        from pypdf import PdfReader, PdfWriter
        with tempfile.TemporaryDirectory(prefix="maya-pro-previews-") as tmp:
            for i, page in enumerate(PdfReader(pdf).pages):
                part = Path(tmp) / "page.pdf"
                jpg = Path(tmp) / "page.jpg"
                writer = PdfWriter(); writer.add_page(page); writer.write(part)
                # Quartz supplies a white background through JPEG, avoiding transparent PNG previews.
                subprocess.run(["sips", "-s", "format", "jpeg", str(part), "--out", str(jpg)], check=True, capture_output=True)
                subprocess.run(["sips", "-s", "format", "png", str(jpg), "--out", str(folder / f"sayfa{i + 1}.png")], check=True, capture_output=True)
    else:
        for i, pg in enumerate(fitz.open(str(pdf))):
            pg.get_pixmap(dpi=110).save(str(folder / f"sayfa{i + 1}.png"))


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data")
    ap.add_argument("-o", "--out", required=True, help="HTML çıktı yolu")
    ap.add_argument("--pdf", default=None)
    ap.add_argument("--png", default=None, help="Sayfa önizlemeleri için klasör")
    ap.add_argument("--force", action="store_true", help="Taşma varsa da PDF'i bas (yalnız taslak için)")
    a = ap.parse_args()
    d = json.loads(Path(a.data).read_text(encoding="utf-8"))
    raw = json.dumps({k: v for k, v in d.items() if not k.startswith("_")}, ensure_ascii=False)
    if MARK in raw and not a.force:
        sys.exit("HATA: data.json'da doldurulmamış ⟪YAZ⟫ alanı var. Önce: python validate_data.py data.json")
    pdf = Path(a.pdf) if a.pdf else None
    if pdf:
        # DECISIONS 278: no PDF unless Maya Audit's release gate ran on this data and found nothing that blocks it.
        # --force never skips it: a draft can still be looked at as HTML.
        from validate_data import gate_check
        record, missing = gate_check(d)
        if missing:
            sys.exit("HATA: " + missing)
        hard = [v for v in record["violations"] if v["hard"]]
        for v in record["violations"]:
            print(("HATA" if v["hard"] else "UYARI") + f": {v['rule']}: {v['message']}")
        if hard:
            sys.exit(f"HATA: yayın kapısı {record['decision']}: {len(hard)} engelleyici ihlal. PDF üretilmedi.")
    out = Path(a.out)
    out.write_text(build_html(d), encoding="utf-8")
    print(f"HTML: {out}")
    if not has_search_or_performance(d):
        print("Arama ve performans sayfası basılmadı: bu denetimde arama, laboratuvar ve saha verisi yok.")
    if has_client_page(d):
        appendix, problems = write_appendix(d, out)
        for line in problems:
            print(line)
        if problems and pdf and not a.force:
            sys.exit(1)
        if appendix:
            print(f"Ek (XLSX, rapora eklenir): {appendix}")
    else:
        addresses = write_address_list(d, out)
        if addresses:
            print(f"Adres listesi (rapora eklenir): {addresses}")
    over = render(out, pdf)
    if over:
        print("TAŞMA: şu alanlar kutusuna sığmıyor, kısaltın:")
        for s in dict.fromkeys(over):
            print("  -", s)
        if pdf and not a.force:
            pdf.unlink(missing_ok=True)
            sys.exit(1)
    if pdf:
        issues = check_pdf(pdf, d)
        for i in issues:
            print(i)
        if any(i.startswith("HATA") for i in issues) and not a.force:
            sys.exit(1)
        print(f"PDF: {pdf}")
        if a.png:
            write_previews(pdf, Path(a.png))
            print(f"PNG: {a.png}")


if __name__ == "__main__":
    main()
