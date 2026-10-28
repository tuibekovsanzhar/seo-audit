"""Generate an offline browser preview; never crawl a real site or use paid APIs.

Run: python3 scripts/stage1_preview.py
"""
from pathlib import Path
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fakeserver.stage1 import mock_site
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.evidence_store import save_evidence
from maya_audit.report import build_report, render_markdown
from maya_audit_web_lite import md_to_html


def main():
    folder = ROOT / 'output' / 'stage1-preview'
    folder.mkdir(parents=True, exist_ok=True)
    transport, seen = mock_site(500)
    cfg = CrawlConfig(max_pages=500, request_delay_s=0, robots_samples=1, render_enabled=False,
                      prf_enabled=False, probes_enabled=False, refetch_delay_s=0, soft_404_probe=False)
    start = time.monotonic()
    outcome = run_audit('http://127.0.0.1/', cfg, transport=transport)
    index = save_evidence(outcome.result, cfg, folder / 'evidence', 'all')
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    markdown = render_markdown(outcome.result, outcome.gates, outcome.checks)
    (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
    (folder / 'report.md').write_text(markdown, encoding='utf-8', newline='\n')
    html = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Maya Audit — Stage 1 offline preview</title>
<style>body{font:16px/1.6 system-ui;margin:40px auto;padding:0 24px;max-width:1000px;color:#252525;background:#fafaf8}
h1,h2{line-height:1.2}h2{margin-top:36px}td,th{border:1px solid #ddd;padding:8px;text-align:left}table{border-collapse:collapse;width:100%}
.tw,pre{overflow:auto}code{overflow-wrap:anywhere}.notice{padding:20px;background:#e8eee9}a{color:#176449}</style>
<div class="notice"><b>Stage 1: offline fixture preview</b><p>These 500 pages are generated test content.
No real website or paid service was contacted. This is a report preview, not the new chat app.
Rendering and optional external data were disabled, and their limits appear below.</p>
<a href="report.md" download>Download Markdown</a> · <a href="report.json" download>Download JSON</a>
</div>'''
    (folder / 'index.html').write_text(html + md_to_html(markdown) + '</html>', encoding='utf-8', newline='\n')
    metrics = {'pages': len(outcome.result.pages), 'mock_requests': len(seen),
               'evidence_pages': len(index['pages']), 'evidence_bytes': index['total_bytes'],
               'json_bytes': (folder / 'report.json').stat().st_size,
               'elapsed_seconds': round(time.monotonic() - start, 3)}
    (folder / 'metrics.json').write_text(json.dumps(metrics, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(metrics, indent=2))
    print(f'Open {folder / "index.html"}')


if __name__ == '__main__':
    main()
