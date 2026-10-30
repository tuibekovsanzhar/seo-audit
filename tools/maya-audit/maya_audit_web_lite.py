#!/usr/bin/env python3
"""Maya Audit Lite: a small local web page for running Maya Audit from the browser.

Superseded by the full web app: run `.venv/bin/python -m maya_audit_web` (http://127.0.0.1:8770, docs/WEB-APP.md).
This older helper still works and is kept for anyone used to it. It does not change the audit:
it runs the existing command line (python -m maya_audit crawl ...) in the background
and shows the Markdown report in the browser.

Run from the project folder:
    .venv/bin/python maya_audit_web_lite.py
then open http://127.0.0.1:8765

Standard library only. Listens on 127.0.0.1 only.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = int(os.environ.get("MAYA_LITE_PORT", "8765"))
PROJECT = Path(__file__).resolve().parent
OUT_ROOT = PROJECT / "output" / "web-lite"
PYTHON = sys.executable
MODES = {"10": 10, "30": 30, "50": 50, "100": 100}
EXIT_MEANING = {
    0: "Completed",
    1: "Degraded: the site could not be read properly",
    2: "Error: no audit was produced",
    3: "Incomplete: stopped at the page cap or time limit (normal for a capped audit)",
}

JOBS: dict[str, dict] = {}
LOCK = threading.Lock()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "site"


def normalise_url(raw: str) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    p = urlparse(raw)
    if p.scheme not in ("http", "https") or not p.hostname or "." not in p.hostname:
        return None
    return f"{p.scheme}://{p.hostname}{p.path or '/'}"


def run_job(job_id: str) -> None:
    job = JOBS[job_id]
    cmd = [
        PYTHON, "-m", "maya_audit", "crawl", job["url"],
        "--max-pages", str(job["pages"]),
        "--json", str(job["dir"] / "report.json"),
        "--markdown", str(job["dir"] / "report.md"),
        # Lite audits public sites typed into a page: localhost and private addresses are refused, as in the full
        # web app (D-11). Local development uses the CLI directly.
        "--block-loopback",
    ]
    if job["backlinks"]:
        cmd.append("--dataforseo")
    job["command"] = " ".join(cmd[1:])
    proc = None
    try:
        # The child prints "→" and page titles; a pipe on Windows defaults to the ANSI code page, so both ends
        # agree on UTF-8 and an unencodable character is replaced rather than ending the audit.
        proc = subprocess.Popen(
            cmd, cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, bufsize=1, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        job["proc"] = proc
        for line in proc.stdout:  # type: ignore[union-attr]
            with LOCK:
                job["log"].append(line.rstrip("\n"))
                job["log"] = job["log"][-400:]
        code = proc.wait()
        with LOCK:
            job["exit"] = code
            job["state"] = "cancelled" if job.get("cancelled") else "done"
    except Exception as exc:  # noqa: BLE001
        with LOCK:
            job["log"].append(f"Could not start the audit: {exc}")
            job["exit"] = 2
            job["state"] = "done"
    finally:
        # A read error leaves the job "done": the child must not go on auditing with no one able to stop it (D-16).
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
    job["ended"] = time.time()


def content_length(value: str | None) -> int | None:
    """The request body's length, or None when the header is not a plain number from 0 to 4096 (D-12): "-1" would
    make read() wait for the end of the connection, and a word would end the request with an unhandled error."""
    value = (value or "0").strip()
    if not (value.isascii() and value.isdigit()) or int(value) > 4096:
        return None
    return int(value)


# ---------- tiny, safe Markdown renderer (escapes everything first) ----------
def inline(text: str) -> str:
    t = html.escape(text, quote=True)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*([^*\s][^*]*)\*(?!\w)", r"<em>\1</em>", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
               r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', t)
    return t


def md_to_html(md: str) -> str:
    out: list[str] = []
    lines = md.splitlines()
    i = 0
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            close_list()
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(html.escape(lines[i]))
                i += 1
            out.append("<pre>" + "\n".join(buf) + "</pre>")
        elif s.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]):
            close_list()
            head = [c.strip() for c in s.strip("|").split("|")]
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            i -= 1
            t = ['<div class="tw"><table><thead><tr>']
            t += [f"<th>{inline(h)}</th>" for h in head]
            t.append("</tr></thead><tbody>")
            for r in rows:
                t.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            t.append("</tbody></table></div>")
            out.append("".join(t))
        elif m := re.match(r"^(#{1,6})\s+(.*)$", s):
            close_list()
            lvl = len(m.group(1))
            txt = m.group(2)
            sev = re.search(r"\[(S[1-4]|Info)\]", txt)
            cls = f' class="sev-{sev.group(1).lower()}"' if sev else ""
            out.append(f"<h{lvl}{cls}>{inline(txt)}</h{lvl}>")
        elif re.match(r"^\s*[-*]\s+", line):
            if not in_list:
                out.append("<ul>")
                in_list = True
            item = re.sub(r"^\s*[-*]\s+", "", line)
            out.append(f"<li>{inline(item)}</li>")
        elif s == "":
            close_list()
        elif s in ("---", "***"):
            close_list()
            out.append("<hr>")
        else:
            close_list()
            out.append(f"<p>{inline(s)}</p>")
        i += 1
    close_list()
    return "\n".join(out)


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Maya Audit Lite</title>
<style>
:root{--bg:#0f1115;--panel:#171a21;--panel2:#1e222b;--text:#e8eaf0;--muted:#9aa3b2;--line:#2a2f3a;--accent:#7c5cff;--accent2:#22c3a6;
--s1:#ff4d5e;--s2:#ff9f43;--s3:#f5d547;--s4:#5fa8ff;--info:#8b95a7}
:root[data-theme=light]{--bg:#f6f7fb;--panel:#fff;--panel2:#f0f2f7;--text:#151820;--muted:#5d6676;--line:#dde1ea}
*{box-sizing:border-box}body{margin:0;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;background:var(--bg);color:var(--text)}
.app{display:grid;grid-template-columns:270px 1fr;height:100vh}
aside{background:var(--panel);border-right:1px solid var(--line);padding:18px;overflow:auto}
.logo{font-weight:800;font-size:18px;display:flex;gap:10px;align-items:center;margin-bottom:18px}
.dot{width:12px;height:12px;border-radius:50%;background:linear-gradient(135deg,var(--accent),var(--accent2))}
.hist h4{margin:16px 0 8px;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}
.hitem{padding:10px;border-radius:10px;cursor:pointer;border:1px solid transparent;margin-bottom:6px}
.hitem:hover{background:var(--panel2);border-color:var(--line)}.hitem b{display:block;font-size:14px}.hitem span{color:var(--muted);font-size:12px}
main{display:flex;flex-direction:column;height:100vh}
.thread{flex:1;overflow:auto;padding:28px 0}
.wrap{max-width:920px;margin:0 auto;padding:0 24px}
.msg{display:flex;gap:12px;margin:0 0 18px}.av{width:34px;height:34px;border-radius:10px;flex:none;display:grid;place-items:center;font-weight:700}
.bot .av{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff}.me{justify-content:flex-end}.me .bubble{background:var(--accent);color:#fff}
.bubble{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px;max-width:100%;overflow:hidden}
.composer{border-top:1px solid var(--line);background:var(--panel);padding:16px 0}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
input[type=text]{flex:1;min-width:260px;padding:13px 14px;border-radius:12px;border:1px solid var(--line);background:var(--panel2);color:var(--text);font-size:15px}
select,button{padding:12px 14px;border-radius:12px;border:1px solid var(--line);background:var(--panel2);color:var(--text);font-size:14px;cursor:pointer}
button.primary{background:linear-gradient(135deg,var(--accent),#5a8bff);color:#fff;border:none;font-weight:600}
button:disabled{opacity:.5;cursor:default}label.chk{color:var(--muted);font-size:13px;display:flex;gap:6px;align-items:center}
.bar{height:8px;background:var(--panel2);border-radius:99px;overflow:hidden;margin:10px 0}.bar i{display:block;height:100%;width:30%;background:linear-gradient(90deg,var(--accent),var(--accent2));animation:mv 1.4s infinite}
@keyframes mv{0%{margin-left:-30%}100%{margin-left:100%}}
pre{background:var(--panel2);padding:10px;border-radius:10px;overflow:auto;font-size:12px;max-height:220px}
.report h1{font-size:22px}.report h2{font-size:18px;margin-top:26px;border-bottom:1px solid var(--line);padding-bottom:6px}.report h3{font-size:15px;margin-top:20px;padding-left:10px;border-left:4px solid var(--line)}
.report h3.sev-s1{border-color:var(--s1)}.report h3.sev-s2{border-color:var(--s2)}.report h3.sev-s3{border-color:var(--s3)}.report h3.sev-s4{border-color:var(--s4)}.report h3.sev-info{border-color:var(--info)}
.tw{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}th{background:var(--panel2)}
code{background:var(--panel2);padding:1px 5px;border-radius:5px;font-size:12.5px;word-break:break-all}a{color:var(--accent2)}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}.chip{padding:3px 10px;border-radius:99px;font-size:12px;font-weight:700;color:#111}
.muted{color:var(--muted);font-size:13px}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
@media print{aside,.composer,.noprint{display:none!important}.app{display:block}.thread{overflow:visible}.bubble{border:none}body{background:#fff;color:#000}}
</style></head><body>
<div class="app"><aside><div class="logo"><span class="dot"></span>Maya Audit <span class="muted">Lite</span></div>
<button onclick="toggleTheme()" style="width:100%">Light / dark</button>
<div class="hist"><h4>Audits</h4><div id="hist"></div></div></aside>
<main><div class="thread" id="thread"><div class="wrap" id="msgs"></div></div>
<div class="composer"><div class="wrap"><div class="row">
<input id="url" type="text" placeholder="Paste a brand's website, e.g. carpexonline.com" onkeydown="if(event.key==='Enter')start()">
<select id="pages"><option value="10">Quick test: 10 pages</option><option value="30" selected>30 pages</option><option value="50">50 pages</option><option value="100">100 pages</option></select>
<label class="chk"><input type="checkbox" id="bl">Backlinks (DataForSEO, ~$0.05)</label>
<button class="primary" id="go" onclick="start()">Audit</button></div>
<div class="muted" style="margin-top:8px">Runs on this computer only. Rough time: 10 pages about 3–4 min, 30 pages about 6–8 min, 100 pages 15+ min.</div></div></div></main></div>
<script>
const $=s=>document.querySelector(s);let current=null,timer=null;
function toggleTheme(){const r=document.documentElement;r.dataset.theme=r.dataset.theme==='light'?'':'light'}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function add(who,html){const d=document.createElement('div');d.className='msg '+(who==='me'?'me':'bot');
d.innerHTML=(who==='me'?'':'<div class="av">M</div>')+'<div class="bubble">'+html+'</div>';$('#msgs').appendChild(d);$('#thread').scrollTop=1e9;return d}
add('bot','<b>Hi!</b> Paste a brand\'s website below and click <b>Audit</b>. I will crawl it, run the technical SEO and AI-readiness checks, and show the report here, with Markdown, JSON and PDF downloads.');
async function start(){const url=$('#url').value.trim();if(!url)return;
const body=new URLSearchParams({url,pages:$('#pages').value,backlinks:$('#bl').checked?'1':''});
add('me',esc(url)+' <span style="opacity:.75">· '+$('#pages').value+' pages'+($('#bl').checked?' · backlinks':'')+'</span>');
const r=await fetch('/api/start',{method:'POST',body,headers:{'X-Maya-Lite':'1'}});const j=await r.json();
if(!r.ok){add('bot','⚠️ '+esc(j.error));return}
current=j.id;$('#go').disabled=true;$('#url').value='';
const m=add('bot','<b>Auditing '+esc(j.url)+'</b><div class="bar"><i></i></div><div class="muted" id="st-'+j.id+'">Starting…</div><details><summary class="muted">Live log</summary><pre id="lg-'+j.id+'"></pre></details><div class="actions noprint"><button onclick="cancel(\''+j.id+'\')">Cancel</button></div>');
m.id='m-'+j.id;poll(j.id);loadHist()}
async function cancel(id){await fetch('/api/cancel?id='+id,{method:'POST',headers:{'X-Maya-Lite':'1'}})}
async function poll(id){const r=await fetch('/api/status?id='+id);const j=await r.json();
const st=$('#st-'+id),lg=$('#lg-'+id);if(st)st.textContent=(j.state==='running'?'Running · ':'')+Math.round(j.elapsed)+' s elapsed';if(lg)lg.textContent=j.log.join('\n');
if(j.state==='running'){timer=setTimeout(()=>poll(id),2000);return}
$('#go').disabled=false;loadHist();show(id)}
async function show(id){const r=await fetch('/api/report?id='+id);const j=await r.json();const old=$('#m-'+id);
let h='<b>'+esc(j.url)+'</b><div class="muted">'+esc(j.exit_meaning)+' · '+Math.round(j.elapsed)+' s</div>';
if(j.counts){h+='<div class="chips">'+Object.entries(j.counts).map(([k,v])=>'<span class="chip" style="background:var(--'+k.toLowerCase()+')">'+k+': '+v+'</span>').join('')+'</div>'}
if(j.html){h+='<div class="actions noprint"><a href="/files/'+id+'/report.md" download><button>Download Markdown</button></a><a href="/files/'+id+'/report.json" download><button>Download JSON</button></a><button onclick="window.print()">Save as PDF</button></div><div class="report">'+j.html+'</div>'}
else{h+='<p>No report was produced.</p><pre>'+esc(j.log.join('\n'))+'</pre>'}
if(old)old.remove();add('bot',h)}
async function loadHist(){const r=await fetch('/api/history');const j=await r.json();
$('#hist').innerHTML=j.map(x=>'<div class="hitem" onclick="show(\''+x.id+'\')"><b>'+esc(x.host)+'</b><span>'+esc(x.when)+' · '+esc(x.status)+'</span></div>').join('')||'<div class="muted">No audits yet</div>'}
loadHist();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "MayaAuditLite"

    def log_message(self, *a):  # quiet
        pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"error": "local access only"})
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8",
                              {"Content-Security-Policy": "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self' data:"})
        if u.path == "/api/status":
            job = JOBS.get(q.get("id", [""])[0])
            if not job:
                return self._json(404, {"error": "unknown audit"})
            with LOCK:
                end = job.get("ended") or time.time()
                return self._json(200, {"state": job["state"], "elapsed": end - job["started"], "log": job["log"][-60:]})
        if u.path == "/api/report":
            job = JOBS.get(q.get("id", [""])[0])
            if not job:
                return self._json(404, {"error": "unknown audit"})
            md_path = job["dir"] / "report.md"
            md = md_path.read_text(encoding="utf-8", errors="replace") if md_path.exists() else ""
            counts = {}
            for sev in ("S1", "S2", "S3", "S4", "Info"):
                n = len(re.findall(rf"^###\s+\d+\.\s+\[{sev}\]", md, re.M))
                if n:
                    counts[sev] = n
            code = job.get("exit")
            return self._json(200, {
                "url": job["url"], "html": md_to_html(md) if md else "", "counts": counts,
                "exit_meaning": "Cancelled" if job.get("cancelled") else EXIT_MEANING.get(code, f"Exit code {code}"),
                "elapsed": (job.get("ended") or time.time()) - job["started"], "log": job["log"][-80:],
            })
        if u.path == "/api/history":
            items = sorted(JOBS.values(), key=lambda j: j["started"], reverse=True)
            return self._json(200, [{
                "id": j["id"], "host": urlparse(j["url"]).hostname,
                "when": datetime.fromtimestamp(j["started"]).strftime("%d %b %H:%M"),
                "status": j["state"] if j["state"] != "done" else EXIT_MEANING.get(j.get("exit"), "done").split(":")[0],
            } for j in items])
        m = re.match(r"^/files/([a-z0-9-]+)/(report\.md|report\.json)$", u.path)
        if m and m.group(1) in JOBS:
            p = JOBS[m.group(1)]["dir"] / m.group(2)
            if p.exists():
                ctype = "text/markdown; charset=utf-8" if p.suffix == ".md" else "application/json"
                host = slug(urlparse(JOBS[m.group(1)]["url"]).hostname or "site")
                return self._send(200, p.read_bytes(), ctype,
                                  {"Content-Disposition": f'attachment; filename="{host}-{m.group(2)}"'})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Maya-Lite") != "1":
            return self._json(403, {"error": "local page only"})
        u = urlparse(self.path)
        if u.path == "/api/start":
            n = content_length(self.headers.get("Content-Length"))
            if n is None:
                return self._json(400, {"error": "The request body must be a short form."})
            form = parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
            url = normalise_url(form.get("url", [""])[0])
            if not url:
                return self._json(400, {"error": "That doesn't look like a website address."})
            pages = MODES.get(form.get("pages", ["30"])[0], 30)
            with LOCK:
                if any(j["state"] == "running" for j in JOBS.values()):
                    return self._json(409, {"error": "An audit is already running. Wait for it to finish or cancel it."})
                job_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + slug(urlparse(url).hostname or "site")
                d = OUT_ROOT / job_id
                d.mkdir(parents=True, exist_ok=True)
                JOBS[job_id] = {"id": job_id, "url": url, "pages": pages, "backlinks": bool(form.get("backlinks", [""])[0]),
                                "dir": d, "state": "running", "log": [], "started": time.time()}
            threading.Thread(target=run_job, args=(job_id,), daemon=True).start()
            return self._json(200, {"id": job_id, "url": url})
        if u.path == "/api/cancel":
            with LOCK:  # read and change the job under the same lock the worker writes it with (D-16)
                job = JOBS.get(parse_qs(u.query).get("id", [""])[0])
                if job and job.get("proc") and job["state"] == "running":
                    job["cancelled"] = True
                    job["proc"].terminate()
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "not found"})


def main():
    if not (PROJECT / "maya_audit").is_dir():
        print("Put this file in the Maya Audit project folder (next to the maya_audit/ folder) and run it from there.")
        sys.exit(1)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Maya Audit Lite is running: open http://{HOST}:{PORT}  (press Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
