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


def _on_a_release_tag() -> bool:
    """Whether this checkout is a release: a `team-preview-*` tag on HEAD (or CI started for one)."""
    import os

    if os.environ.get("GITHUB_REF_TYPE") == "tag" and os.environ.get("GITHUB_REF_NAME", "").startswith("team-preview-"):
        return True
    if not _in_git_checkout():
        return False
    found = subprocess.run(["git", "tag", "--points-at", "HEAD", "--list", "team-preview-*"], cwd=ROOT,
                           capture_output=True, text=True)
    return bool(found.stdout.strip())


def test_snapshot_and_checkpoint_state_the_applications_version():
    """The snapshot and the checkpoint describe the last release, as release preparation wrote them. Between releases the
    code's report schema may be ahead of it (DECISIONS 295): never behind, and the release's own frozen schema is kept.
    On a release tag the two must be equal."""
    from maya_audit.schema import frozen_path, version_key

    assert SNAPSHOT["application_version"] == __version__
    line = f"Release {SNAPSHOT['release']} / application {__version__} / schema {SNAPSHOT['schema_version']}."
    assert line in CHECKPOINT
    assert re.fullmatch(r"w\d+[a-z]?", SNAPSHOT["release"])  # a fix after a release is the next letter (w14b)
    assert version_key(SNAPSHOT["schema_version"]) <= version_key(SCHEMA_VERSION)
    assert frozen_path(SNAPSHOT["schema_version"]).is_file()
    if _on_a_release_tag():
        assert SNAPSHOT["schema_version"] == SCHEMA_VERSION


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


def _in_git_checkout() -> bool:
    # The repository root is above this folder (tools/maya-audit), so ask Git rather than look for ROOT / ".git".
    return bool(shutil.which("git")) and subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT,
                                                        capture_output=True, text=True).stdout.strip() == "true"


@pytest.mark.skipif(not _in_git_checkout(), reason="not a Git checkout")
def test_git_archive_leaves_out_every_private_path():
    probes = ["benchmarks/real-sites/sites.json", "reviews/review.pdf", ".env", ".claude/settings.json"]
    out = subprocess.run(["git", "check-attr", "export-ignore", "--", *probes], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout
    assert out.count(": export-ignore: set") == len(probes), out
    assert all(p not in SNAPSHOT["files"] for p in release_metadata.shipped_files() if release_metadata.excluded(p))
