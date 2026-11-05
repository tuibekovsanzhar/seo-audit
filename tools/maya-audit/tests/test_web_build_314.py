"""DECISIONS 314: one version per running app. Every text key the page uses exists in Turkish and English; the page's
files come from the process's start-up snapshot with a version token; the page says "restart" when the code on disk is
newer; a missing key is never shown raw; the derived copy is made again when the engine or a text library changes."""
from __future__ import annotations

import json
import re
from pathlib import Path

from maya_audit_web import build, strings
from test_web_app import API, web  # noqa: F401  (fixture)
from test_web_ux_310 import _browser, _page

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
TR = json.loads((ROOT / "maya_audit_web" / "locales" / "tr.json").read_text(encoding="utf-8"))


def _literal_keys() -> set[str]:
    return set(re.findall(r'\bT\(\s*"([a-z0-9_]+(?:\.[a-z0-9_]+)+)"', JS))


def test_every_text_key_the_page_uses_exists_in_english_and_in_turkish():
    keys = _literal_keys()
    assert len(keys) > 300  # the scan finds the page's keys
    english = strings.STRINGS["en"]
    assert sorted(k for k in keys if k not in english) == []
    assert sorted(k for k in keys if k not in TR) == []
    for key in ("result.business.chip", "result.business.why", "result.business.suggested_mark", "app.restart_needed"):
        assert key in english and key in TR


def test_every_key_built_from_a_prefix_has_entries_in_both_languages():
    prefixes = set(re.findall(r'\bT\(\s*"([a-z0-9_.]+\.)"\s*\+', JS))
    assert prefixes
    for prefix in prefixes:
        assert any(k.startswith(prefix) for k in strings.STRINGS["en"]), prefix
        assert any(k.startswith(prefix) for k in TR), prefix


def test_a_missing_key_is_said_in_english_or_as_an_ellipsis_never_raw():
    sync_playwright = _browser()
    with sync_playwright() as pw:
        browser, page, errors = _page(pw)
        got = page.evaluate("""() => {
            state.strings = { "a.b": "Türkçe" }; state.fallback = { "only.english": "English" };
            return [T("a.b"), T("only.english"), T("result.nothing.here")];
        }""")
        assert got == ["Türkçe", "English", "…"]
        browser.close()


def test_the_page_files_are_the_start_up_snapshot_with_a_version_token(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text('<link href="/static/app.css"><script src="/static/app.js"></script>')
    (static / "app.js").write_text("one")
    (static / "app.css").write_text("css")
    snap = build.Snapshot.take(static)
    (static / "app.js").write_text("two")  # an update on disk does not reach the running process
    assert snap.files["app.js"] == b"one"
    assert f'/static/app.js?v={snap.build}'.encode() in snap.index and f'/static/app.css?v={snap.build}'.encode() in snap.index


def test_the_app_serves_the_snapshot_revalidated_and_says_when_a_restart_is_needed(web, monkeypatch):  # noqa: F811
    client = web()
    page = client.get("/")
    token = re.search(r'/static/app\.js\?v=([0-9a-f]{12})', page.text).group(1)
    js = client.get(f"/static/app.js?v={token}")
    assert js.status_code == 200 and js.headers["cache-control"] == "no-cache" and token in js.headers["etag"]
    assert js.text == (ROOT / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    assert client.get("/static/app.js", headers={"If-None-Match": js.headers["etag"]}).status_code == 304
    assert client.get("/static/nothing.js").status_code == 404
    info = client.get(f"{API}/version").json()
    assert info["build"] == token and info["restart_needed"] is False and info["engine"]["fingerprint"]
    monkeypatch.setattr(build, "code_fingerprint", lambda *a, **k: "0000000000000000")
    monkeypatch.setattr(build, "CHECK_EVERY_S", 0.0)
    assert client.get(f"{API}/version").json()["restart_needed"] is True


def test_the_derived_copy_is_made_again_when_a_text_library_changes(monkeypatch):
    from maya_audit_web.team_report import current
    texts = (ROOT / "maya_audit_web" / "team_report" / "texts" / "tr.json").resolve()
    real = Path.read_bytes
    current.fingerprint.cache_clear()
    before = current.fingerprint()
    monkeypatch.setattr(Path, "read_bytes", lambda self: real(self) + (b" " if self.resolve() == texts else b""))
    current.fingerprint.cache_clear()
    changed = current.fingerprint()
    monkeypatch.undo()
    current.fingerprint.cache_clear()
    assert changed != before and current.fingerprint() == before


def test_the_report_column_and_the_chat_bar_are_centred_beside_the_sidebar_at_any_width():
    """The real page and stylesheet, a finished audit's card (class job-done, which sat on the left) and a plain card:
    equal empty margins left and right at 1440, 1920 and 2560 px and at 67% zoom; the full width at 1024 px."""
    sync_playwright = _browser()
    static = ROOT / "maya_audit_web" / "static"
    html, css = (static / "index.html").read_text(encoding="utf-8"), (static / "app.css").read_text(encoding="utf-8")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, zoom in ((1024, 1), (1440, 1), (1920, 1), (2560, 1), (1440, 0.67)):
            ctx = browser.new_context(viewport={"width": round(width / zoom), "height": 900}, device_scale_factor=zoom)
            page = ctx.new_page()
            page.route("**/*", lambda r: r.fulfill(status=200, content_type="text/css", body=css) if r.request.url.endswith(".css")
                       else r.fulfill(status=200, content_type="text/html", body=html) if r.request.url == "http://maya.test/"
                       else r.abort())
            page.goto("http://maya.test/")
            got = page.evaluate("""() => {
                const thread = document.getElementById("thread");
                document.getElementById("composer").hidden = false;
                for (const cls of ["job-done", "card"]) { const s = document.createElement("section"); s.className = cls; s.textContent = "x"; thread.append(s); }
                const area = thread.getBoundingClientRect(), inner = thread.clientWidth;
                const side = (el) => { const r = el.getBoundingClientRect(); return [Math.round(r.left - area.left), Math.round(area.left + inner - r.right)]; };
                return { cards: [...thread.children].map(side), chat: side(document.querySelector(".composer-row")), inner };
            }""")
            for left, right in got["cards"] + [got["chat"]]:
                assert abs(left - right) <= 1, (width, zoom, got)
            if width == 1024:
                assert got["cards"][0][0] <= 40  # small widths: the column fills the space (only the gutter)
            ctx.close()
        browser.close()
