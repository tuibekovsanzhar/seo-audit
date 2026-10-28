"""Runtime metadata compatibility retained from archive; protected workflow tests deliberately deferred (review R13, H42, H43).

README named version 0.2.0 and schema 1.14 while the package was 0.2.6 with schema 1.16; the skills described a
release process (commit, tag, zip from the tag) that preview-23 did not follow and a POSIX-only environment.
"""

import re
import tomllib
from pathlib import Path

from maya_audit import __version__
from maya_audit.schema import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
SKILLS = sorted((ROOT / ".agents/skills").glob("*/SKILL.md"))


def test_readme_title_and_schema_match_the_package():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert readme.splitlines()[0] == f"# Maya Audit {project['version']} — standalone tool"
    assert project["version"] == __version__
    assert f"(now `{SCHEMA_VERSION}`)" in readme
    assert f"docs/report-schema-{SCHEMA_VERSION}.json" in readme
    assert (ROOT / f"docs/report-schema-{SCHEMA_VERSION}.json").exists()


def test_dependency_lower_bounds_have_no_known_advisory_floor():
    extras = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    for name in ("dev", "web", "team"):
        assert "pypdf>=6.19" in extras[name], name
        assert "starlette>=1.3.1" in extras[name], name
        assert any(re.fullmatch(r"fastapi>=0\.1(3[5-9]|[4-9]\d)", r) for r in extras[name]), name


