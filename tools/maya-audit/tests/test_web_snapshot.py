"""The kept result of a finished audit: it reads back whole, and a planted file cannot run anything."""

from __future__ import annotations

import json
import os
import pickle

import httpx

from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.report import build_report
from maya_audit_web import snapshot
from test_firecrawl import challenged, no_lookups  # noqa: F401  (fixture)
from test_review_fixes import QUIET


def test_a_blocked_audits_result_is_kept_and_reads_back_to_the_same_report(tmp_path, no_lookups):  # noqa: F811
    config = CrawlConfig(**{**QUIET, "max_pages": 10})
    outcome = run_audit("https://bank.test/", config, httpx.MockTransport(challenged))
    assert snapshot.save(tmp_path, outcome, config) and snapshot.exists(tmp_path)
    if os.name != "nt":  # POSIX permission bits only
        assert (tmp_path / snapshot.NAME).stat().st_mode & 0o777 == 0o600
    again, settings = snapshot.load(tmp_path)
    def report(o):
        value=build_report(o.result,o.gates,o.checks)
        # Processing is new; source collection/check evidence and all other metadata must remain identical.
        assert value['generation'].pop('processed_at')
        return json.dumps(value,sort_keys=True,default=str)
    assert report(again) == report(outcome) and settings == config
    snapshot.remove(tmp_path)
    assert not snapshot.exists(tmp_path) and snapshot.load(tmp_path) is None


class _Runs:
    def __reduce__(self):
        return (os.system, ("touch planted-proof",))


def test_a_planted_file_is_refused_and_runs_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for planted in (pickle.dumps(_Runs()), pickle.dumps({"version": 1, "outcome": _Runs(), "config": None}),
                    pickle.dumps({"version": 1, "outcome": print, "config": None}),
                    # a function of the engine itself is refused too: only data classes and enumerations are rebuilt
                    pickle.dumps({"version": 1, "outcome": run_audit, "config": None}),
                    b"not a pickle", pickle.dumps({"version": 99, "outcome": None, "config": None})):
        (tmp_path / snapshot.NAME).write_bytes(planted)
        assert snapshot.load(tmp_path) is None
    assert not (tmp_path / "planted-proof").exists()
    target = tmp_path / "elsewhere"
    target.write_bytes(pickle.dumps({"version": 1, "outcome": None, "config": None}))
    (tmp_path / snapshot.NAME).unlink()
    (tmp_path / snapshot.NAME).symlink_to(target)
    assert snapshot.load(tmp_path) is None and not snapshot.exists(tmp_path)  # a link is never followed


def test_a_result_that_cannot_be_kept_safely_is_simply_not_kept(tmp_path):
    assert snapshot.save(tmp_path, lambda: None, None) is False and not snapshot.exists(tmp_path)
