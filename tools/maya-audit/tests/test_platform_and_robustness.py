"""Phase 0 of the review fixes: the tool installs and runs on every platform it claims, and one bad input never ends
an audit. Each test names the fix it guards (H01-H08 in the fix plan)."""

from __future__ import annotations

import compileall
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx

from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.dataforseo.cache import Cache
from maya_audit.dataforseo.credentials import read_env_file
from maya_audit.fetcher import Fetcher
from maya_audit.firecrawl import reader
from maya_audit.firecrawl.client import WebsiteLoadError
from maya_audit.firecrawl.settings import Options
from maya_audit.report import write_markdown
from maya_audit.robots import policy_from_response
from maya_audit.urls import normalize_url, remove_dot_segments
from test_review_fixes import QUIET

ROOT = Path(__file__).resolve().parents[1]
HTML = {"content-type": "text/html; charset=utf-8"}


# H01 -----------------------------------------------------------------------------------------------------------------
def test_every_module_compiles_on_the_running_python():
    """pyproject says >=3.11; CI runs this on 3.11 too, where nested same-quote f-strings are a SyntaxError."""
    for folder in ("maya_audit", "maya_audit_web", "tests"):
        assert compileall.compile_dir(str(ROOT / folder), quiet=1, force=True, legacy=False), folder
    assert compileall.compile_file(str(ROOT / "maya_audit_web_lite.py"), quiet=1, force=True)


# H02 -----------------------------------------------------------------------------------------------------------------
def test_a_console_that_cannot_encode_an_arrow_does_not_end_the_audit():
    """A redirected stdout on Windows is the ANSI code page; "→" used to raise before the reports were written."""
    code = "from maya_audit.cli import _tolerant_console; _tolerant_console(); print('robots.txt → parsed')"
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, timeout=60,
                          env={**os.environ, "PYTHONIOENCODING": "cp1252"})
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    assert done.stdout.startswith(b"robots.txt ? parsed")


# H03 -----------------------------------------------------------------------------------------------------------------
def test_firecrawl_rendering_survives_an_unreadable_page():
    """render_fallback used names it never defined: the first unreadable page raised UnboundLocalError."""
    page = "<html><head><title>Home</title></head><body><main><h1>Home</h1><p>" + "word " * 200 + "</p></main></body></html>"

    def site(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
        links = '<a href="/a">A</a><a href="/b">B</a>'
        return httpx.Response(200, headers=HTML, text=page.replace("</main>", links + "</main>"))

    cfg = CrawlConfig(**{**QUIET, "max_pages": 5})
    outcome = run_audit("https://app.test/", cfg, httpx.MockTransport(site))
    answers = iter([WebsiteLoadError(500, "All scraping engines failed"), None, None, None, None])

    class Client:
        def scrape(self, url, wait_ms=0):
            answer = next(answers)
            if answer is not None:
                raise answer
            return SimpleNamespace(html=page, status=200, cached=False)

    info: dict = {}
    checks = reader.render_fallback(outcome.result, cfg, Client(), Options(render_fallback=True), info)
    outcomes = [row["outcome"] for row in info["rendered"]]
    assert outcomes[0] == "failed" and "rendered" in outcomes and checks


# H04 / H21 -----------------------------------------------------------------------------------------------------------
def test_the_url_judged_against_robots_is_the_url_that_is_sent():
    assert remove_dot_segments("/public/../private/x") == "/private/x"
    assert remove_dot_segments("/a/./b/../c/") == "/a/c/"
    assert remove_dot_segments("/../../etc") == "/etc"
    assert remove_dot_segments("/file.v2.html") == "/file.v2.html"
    assert normalize_url("http://h.example/public/../private/x") == "http://h.example/private/x"
    assert normalize_url("http://EXAMPLE.com./a?q=1#frag") == "http://example.com/a?q=1"


def test_a_link_with_a_control_character_is_one_bad_link_not_a_dead_crawl():
    assert normalize_url("/x\x01y", "http://h.example/") is None
    fetcher = Fetcher("Maya-Audit-test", 1, 0, httpx.MockTransport(lambda request: httpx.Response(200)))
    answer = fetcher.get("http://h.example/x\x01y", "page", 1000)
    assert answer.status is None and answer.error.startswith("invalid_url")

    def site(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n", headers={"content-type": "text/plain"})
        if request.url.path.startswith("/private"):
            raise AssertionError(f"robots.txt disallows {request.url.path}, and it was requested")
        body = ('<html><head><title>Home</title></head><body><h1>Home</h1>'
                '<a href="/x\x01y">bad</a><a href="http://shop.test/public/../private/abs">sneaky</a>'
                '<a href="/public/ok">ok</a></body></html>')
        return httpx.Response(200, headers=HTML, text=body)

    outcome = run_audit("http://shop.test/", CrawlConfig(**{**QUIET, "max_pages": 10}), httpx.MockTransport(site))
    read = {p.url for p in outcome.result.pages}
    assert "http://shop.test/public/ok" in read and not any("/private" in url for url in read)


def test_a_robots_file_with_a_byte_order_mark_is_obeyed():
    body = "﻿User-agent: *\nDisallow: /a\n".encode("utf-8")
    policy = policy_from_response("https://h.example/robots.txt", 200, None, body, 500_000, [])
    assert policy.decide("Maya-Audit", "https://h.example/a").allowed is False
    assert policy.decide("Maya-Audit", "https://h.example/b").allowed is True


# H05 -----------------------------------------------------------------------------------------------------------------
def test_an_env_file_saved_with_a_byte_order_mark_keeps_its_first_key(tmp_path):
    env = tmp_path / ".env"
    env.write_bytes("﻿MAYA_AUDIT_X=1\nMAYA_AUDIT_Y=2\n".encode("utf-8"))
    assert read_env_file(env) == {"MAYA_AUDIT_X": "1", "MAYA_AUDIT_Y": "2"}


def test_an_env_file_saved_as_utf16_is_named_not_crashed_on(tmp_path):
    env = tmp_path / ".env"
    env.write_bytes("MAYA_AUDIT_X=1\n".encode("utf-16"))
    try:
        read_env_file(env)
    except ValueError as exc:
        assert "UTF-8" in str(exc)
    else:
        raise AssertionError("a UTF-16 .env file was read without a word")


# H06 -----------------------------------------------------------------------------------------------------------------
def test_the_cache_leaves_no_open_handle_on_its_file(tmp_path):
    cache = Cache(tmp_path / "c" / "dataforseo-cache.db")
    cache.put("/v3/x", {"a": 1}, {"ok": True})
    assert cache.get("/v3/x", {"a": 1}, 3600)[0] == {"ok": True}
    (tmp_path / "c" / "dataforseo-cache.db").unlink()  # WinError 32 here while a connection stayed open


# H07 -----------------------------------------------------------------------------------------------------------------
def test_reports_are_written_with_the_same_bytes_on_every_platform(tmp_path):
    target = tmp_path / "r.md"
    write_markdown("# Title\n\nline\n", str(target))
    assert target.read_bytes() == b"# Title\n\nline\n"


def test_a_snapshot_reads_enum_members_pickled_the_python_311_way_and_nothing_else():
    """Python 3.11 pickles an enum member as getattr(EnumClass, "MEMBER"); the allowlist refused it, so no snapshot
    was ever kept on 3.11. Only a real member of an allowed enum is accepted, never getattr in general."""
    import io
    import pickle

    import pytest

    from maya_audit.findings import Severity
    from maya_audit_web import snapshot

    class Member:  # reduces the way Python 3.11 reduces an enum member

        def __reduce__(self):
            return getattr, (Severity, "S1")
    assert snapshot._OnlyData(io.BytesIO(pickle.dumps(Member(), protocol=4))).load() is Severity.S1

    class NotAMember:
        def __reduce__(self):
            return getattr, (Severity, "__class__")
    with pytest.raises(snapshot.Refused):
        snapshot._OnlyData(io.BytesIO(pickle.dumps(NotAMember(), protocol=4))).load()
