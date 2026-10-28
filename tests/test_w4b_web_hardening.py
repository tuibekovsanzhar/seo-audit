"""Web app and Lite hardening from the preview-23 review, section D (D-07, D-10, D-11, D-12, D-13, D-16..D-20, D-24, D-25).
Local only: an in-process app, fake processes and fake sockets; nothing listens on a port."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import pickle
import socket
import sys
import zipfile
from pathlib import Path, PureWindowsPath

import pytest

pytest.importorskip("fastapi")

from maya_audit_web import analyses, demo, snapshot  # noqa: E402
from test_report_agreement import audit, demo_app  # noqa: E402,F401
from test_web_app import API  # noqa: E402

import maya_audit_web_lite as lite  # noqa: E402


def test_the_evidence_zip_names_no_folder_of_this_computer(demo_app, tmp_path):
    one = audit(demo_app, demo.CAFE)
    folder = demo_app.app.state.runner.artifacts(one["id"]) / "evidence"
    index = folder / "index.json"
    if not index.is_file():  # an audit that saved no page evidence: give it an index as an older version wrote it
        folder.mkdir(parents=True, exist_ok=True)
        index.write_text(json.dumps({"pages": []}), encoding="utf-8")
    saved = json.loads(index.read_text(encoding="utf-8"))
    saved["folder"] = str(folder)  # what evidence_store wrote before D-07: the absolute path, with the user's name
    index.write_text(json.dumps(saved), encoding="utf-8")
    zipped = demo_app.get(f"{API}/audits/{one['id']}/downloads/evidence")
    assert zipped.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as archive:
        everything = b"".join(archive.read(name) for name in archive.namelist()).decode("utf-8", "replace")
        assert json.loads(archive.read("evidence/index.json"))["folder"] == "evidence"
    for needle in (str(tmp_path), str(Path.home()), str(tmp_path).replace("\\", "\\\\"), "C:\\Users", "/home/"):
        assert needle not in everything, needle
    assert json.loads(index.read_text(encoding="utf-8"))["folder"] == str(folder)  # the saved file is not rewritten


def test_a_revised_analysis_manifest_is_read_as_utf8_and_its_report_hashed_once(tmp_path, monkeypatch):
    identity = "analysis-kafe-r1"
    artifacts = tmp_path / identity / "artifacts"
    artifacts.mkdir(parents=True)
    data = json.dumps({"schema_version": "1.17"}).encode()
    (artifacts / "report.json").write_bytes(data)
    label = "Kafe — gözden geçirilmiş kanıt (İş)"
    meta = {"id": identity, "label": label, "processed_at": "2026-10-21T10:00:00+00:00", "analysis_version": "v1",
            "source_audit_id": "a" * 32, "report_sha256": hashlib.sha256(data).hexdigest()}
    (tmp_path / identity / "analysis.json").write_text(json.dumps({"analysis": meta, "audit": {"id": identity, "state": "finished"}},
                                                                  ensure_ascii=False), encoding="utf-8")
    registry = analyses.Registry(tmp_path)
    reads = []
    from types import SimpleNamespace
    # Only the registry's own reference to hashlib is replaced: nothing else in the process hashes through this.
    monkeypatch.setattr(analyses, "hashlib", SimpleNamespace(sha256=lambda value=b"": reads.append(1) or hashlib.sha256(value)))
    assert registry.get(identity)["analysis"]["label"] == label  # not the Windows code page's mojibake (D-10)
    assert registry.get(identity) and len(reads) == 1  # the second request reuses the digest
    (artifacts / "report.json").write_bytes(data.replace(b"1.17", b"1.99"))  # same size, new content and stamp
    assert registry.get(identity) is None and len(reads) == 2


def test_revised_analyses_live_under_the_data_home(tmp_path, monkeypatch):
    from maya_audit_web import __main__ as entry, store
    monkeypatch.setattr(store, "data_home", lambda: tmp_path / "home")
    seen = {}
    monkeypatch.setattr("maya_audit_web.app.create_app", lambda folder, **kw: seen.update(kw, folder=folder) or object())
    entry.build(False, 8770)
    assert seen["analysis_folder"] == tmp_path / "home" / "analyses" and seen["folder"] == tmp_path / "home"  # D-25


def test_a_failed_job_leaves_its_traceback_in_the_server_log_and_only_its_kind_on_the_page(demo_app, monkeypatch):
    runner = demo_app.app.state.runner
    def broken(*_args, **_kwargs):
        raise RuntimeError("C:\\Users\\someone\\secret-path went wrong")
    monkeypatch.setattr(runner, "_audit", broken)
    one = audit(demo_app, demo.CAFE)
    assert one["state"] == "failed" and "RuntimeError" in one["error"]["message"]
    assert "secret-path" not in json.dumps(one)
    log = demo_app.app.state.store.folder / "logs" / "maya-audit-web.log"
    for handler in logging.getLogger("maya_audit_web").handlers:
        handler.flush()
    text = log.read_text(encoding="utf-8")
    assert f"audit {one['id']} failed" in text and "Traceback" in text and "secret-path" in text  # D-13


def test_an_operating_system_error_never_reaches_the_page_with_its_path(demo_app, monkeypatch):
    from maya_audit_web import client_reports
    one = audit(demo_app, demo.CAFE)
    def missing(self):
        raise FileNotFoundError(2, "No such file or directory", "C:\\Users\\someone\\private\\client-report.json")
    monkeypatch.setattr(client_reports.Workspace, "load", missing)
    response = demo_app.get(f"{API}/audits/{one['id']}/client-report")
    assert response.status_code == 404 and "someone" not in response.text and "Önce müşteri taslağını oluşturun" in response.text  # D-18


def test_a_length_or_event_id_in_other_digits_is_refused_not_a_server_error(demo_app):
    one = audit(demo_app, demo.CAFE)
    response = demo_app.post(f"{API}/plans", content=b"{}", headers={"content-type": "application/json", "content-length": "²".encode("latin-1")})
    assert response.status_code in (400, 413)  # never 500 (D-19)
    events = demo_app.get(f"{API}/audits/{one['id']}/events", headers={"last-event-id": "²".encode("latin-1")})
    assert events.status_code == 200 and "event: end" in events.text


def test_deleting_an_audit_is_one_transaction_and_says_which_files_stayed(demo_app, monkeypatch):
    store = demo_app.app.state.store
    one, two = audit(demo_app, demo.CAFE), audit(demo_app, demo.CAFE)
    real = store._db
    class Failing:
        def __init__(self): self.calls = 0
        def execute(self, sql, args=()):
            if sql.startswith("DELETE FROM audits"):
                raise RuntimeError("disk full")
            return real.execute(sql, args)
    store._db = Failing()
    try:
        with pytest.raises(RuntimeError):
            store.delete_audit(one["id"])
    finally:
        store._db = real
    assert store.audit(one["id"]) and store.events(one["id"], after=0, limit=5)  # rolled back: nothing half gone (D-20)
    held = demo_app.app.state.runner.artifacts(two["id"]) / "report.json"
    original = Path.unlink
    def locked(path, *args, **kwargs):
        if path == held:
            raise PermissionError(32, "in use")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", locked)
    answer = demo_app.delete(f"{API}/audits/{two['id']}").json()
    assert answer["deleted"] == two["id"] and answer["files_left"] == 1 and "1 file" in answer["note"]
    monkeypatch.setattr(Path, "unlink", original)
    assert demo_app.delete(f"{API}/audits/{one['id']}").json() == {"deleted": one["id"]}


def test_the_port_probe_on_windows_asks_for_the_port_alone():
    from maya_audit_web import __main__ as entry
    calls = []
    class Probe:
        def setsockopt(self, *args):
            calls.append(args)
    entry.probe_options(Probe(), platform="win32")
    assert calls and calls[0][1] != socket.SO_REUSEADDR and calls[0][1] == getattr(socket, "SO_EXCLUSIVEADDRUSE", -5)  # D-17
    calls.clear()
    entry.probe_options(Probe(), platform="linux")
    assert calls[0][1] == socket.SO_REUSEADDR


def test_lite_refuses_odd_lengths_blocks_loopback_and_never_leaves_a_child_running(tmp_path, monkeypatch):
    assert lite.content_length("12") == 12 and lite.content_length(None) == 0
    assert [lite.content_length(v) for v in ("-1", "²", "abc", "4097")] == [None] * 4  # D-12
    started = {}
    class Child:
        killed = False
        def __init__(self, cmd, **kwargs):
            started["cmd"] = cmd
            self.stdout = self
        def __iter__(self):
            raise OSError("the pipe broke")  # a read error part-way through the audit
        def poll(self):
            return None if not self.killed else -9
        def kill(self):
            Child.killed = True
        def wait(self):
            return -9
    monkeypatch.setattr(lite.subprocess, "Popen", Child)
    lite.JOBS["w4b"] = {"id": "w4b", "url": "https://shop.example/", "pages": 10, "backlinks": False, "dir": tmp_path,
                        "state": "running", "log": [], "started": 0}
    try:
        lite.run_job("w4b")
        assert "--block-loopback" in started["cmd"]  # D-11
        assert Child.killed and lite.JOBS["w4b"]["state"] == "done"  # D-16: no orphan audit keeps running
    finally:
        lite.JOBS.pop("w4b", None)


def test_a_snapshot_may_hold_a_windows_path():
    for value in (PureWindowsPath("C:/audit/state"), Path("state")):
        loaded = snapshot._OnlyData(io.BytesIO(pickle.dumps({"where": value}))).load()
        assert loaded["where"] == value  # D-24
    with pytest.raises(pickle.UnpicklingError):
        snapshot._OnlyData(io.BytesIO(pickle.dumps(sys.exit))).load()
