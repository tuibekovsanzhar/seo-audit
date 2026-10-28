"""Failure persistence must not depend on a server log sink completing."""
import threading
from types import SimpleNamespace

import pytest

from maya_audit_web.runner import Runner
from maya_audit_web import runner as worker_module


@pytest.mark.parametrize('logging_error', [False, True])
def test_worker_persists_terminal_error_before_a_blocked_or_failing_logger(monkeypatch, logging_error):
    row = {'id': 'synthetic-job', 'state': 'queued', 'language': 'en'}
    events = []
    store = SimpleNamespace(
        next_queued=lambda: dict(row) if row['state'] == 'queued' else None,
        audit=lambda identity: dict(row),
        update_audit=lambda identity, **values: row.update(values),
        add_event=lambda identity, kind, data: events.append((kind, data)),
    )
    def move(identity, allowed, state):
        assert row['state'] in allowed
        row['state'] = state
        return True
    store.move_audit = move
    entered, release = threading.Event(), threading.Event()
    def log(*args, **kwargs):
        entered.set()
        assert release.wait(5), 'test must release its own logger'
        if logging_error:
            raise OSError('synthetic unavailable log sink')
    monkeypatch.setattr(worker_module.log, 'exception', log)
    instance = Runner.__new__(Runner)
    instance.store = store
    instance._closing = threading.Event()
    instance._wake = threading.Event()
    instance._stop = threading.Event()
    instance._current = None
    def fail(*args):
        raise RuntimeError('synthetic worker failure')
    instance._audit = fail
    crashed = []
    def run():
        try:
            instance._loop()
        except Exception as exc:
            crashed.append(type(exc).__name__)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        assert entered.wait(3)
        assert row['state'] == 'failed'
        assert row['error_code'] == 'internal_error' and row['finished_at']
        assert any(kind == 'done' and data['state'] == 'failed' for kind, data in events)
    finally:
        instance._closing.set()
        instance._wake.set()
        release.set()
        thread.join(3)
    assert not thread.is_alive() and not crashed
