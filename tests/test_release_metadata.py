"""Release metadata names the application's own version, and the archive leaves out private data (DECISIONS 283 (7))."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from maya_audit import __version__
from maya_audit.schema import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import release_metadata  # noqa: E402

SNAPSHOT = json.loads((ROOT / "RELEASE-SNAPSHOT.json").read_text(encoding="utf-8"))
CHECKPOINT = (ROOT / "CHECKPOINT-VERIFICATION.md").read_text(encoding="utf-8")
PRIVATE = ("benchmarks/real-sites/", "reviews/", ".env", ".claude/")


def test_snapshot_and_checkpoint_state_the_applications_version():
    assert SNAPSHOT["application_version"] == __version__
    assert SNAPSHOT["schema_version"] == SCHEMA_VERSION
    line = f"Release {SNAPSHOT['release']} / application {__version__} / schema {SCHEMA_VERSION}."
    assert line in CHECKPOINT
    assert re.fullmatch(r"w\d+", SNAPSHOT["release"])


def test_the_snapshot_lists_no_private_path():
    assert set(PRIVATE) <= set(SNAPSHOT["excluded_paths"])
    leaked = [p for p in SNAPSHOT["files"] if p == ".env" or p.startswith((".env.local", "benchmarks/real-sites/",
                                                                              "reviews/", ".claude/"))]
    assert leaked == []


def test_env_files_are_excluded_but_the_template_is_not():
    assert release_metadata.excluded(".env") and release_metadata.excluded(".env.production")
    assert not release_metadata.excluded(".env.example")
    assert release_metadata.excluded("benchmarks/real-sites/carpex/expected.yaml")
    assert not release_metadata.excluded("benchmarks/README.md")


@pytest.mark.skipif(not (ROOT / ".git").exists() or not shutil.which("git"), reason="not a Git checkout")
def test_git_archive_leaves_out_every_private_path():
    probes = ["benchmarks/real-sites/sites.json", "reviews/review.pdf", ".env", ".claude/settings.json"]
    out = subprocess.run(["git", "check-attr", "export-ignore", "--", *probes], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout
    assert out.count(": export-ignore: set") == len(probes), out
    assert all(p not in SNAPSHOT["files"] for p in release_metadata.shipped_files() if release_metadata.excluded(p))
