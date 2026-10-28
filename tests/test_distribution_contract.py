"""The installed package carries every data file the engine reads (implementation guide stage 01).

The 0.2.8 wheel left out `rule_ids.json` and `rule_actions.json`: an installed copy could not resolve a rule id.
The first two tests read pyproject.toml only and always run. The wheel tests build and install a real wheel; they run
offline, so they need the setuptools build backend in this environment or a wheel named by MAYA_AUDIT_WHEEL
(`tools/check_installed_package.py` does the same check with build isolation).
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import check_installed_package as dist  # noqa: E402

NOT_DATA = {".py", ".pyc"}


def _package_data() -> dict[str, list[str]]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return config["tool"]["setuptools"]["package-data"]


def _packages() -> dict[Path, str]:
    """Every directory setuptools packages (it has __init__.py), by its dotted name."""
    return {init.parent: ".".join(init.parent.relative_to(ROOT).parts)
            for top in ("maya_audit", "maya_audit_web") for init in (ROOT / top).rglob("__init__.py")
            if "__pycache__" not in init.parts}


def test_rule_resources_declared_as_package_data():
    declared = _package_data().get("maya_audit", [])
    assert "rule_ids.json" in declared and "rule_actions.json" in declared


def test_package_data_covers_every_resource_file():
    """A data file in a package directory that no package-data pattern matches would be left out of the wheel."""
    packages = _packages()
    data = _package_data()
    declared = {p for folder, name in packages.items() for pattern in data.get(name, []) for p in folder.glob(pattern)}
    left_out = []
    for folder in packages:
        for path in folder.rglob("*"):
            if (path.is_file() and path.suffix not in NOT_DATA and "__pycache__" not in path.parts
                    and path.name != ".DS_Store" and path not in declared):
                owner = max((p for p in packages if p in path.parents), key=lambda p: len(p.parts))
                if owner == folder:
                    left_out.append(str(path.relative_to(ROOT)))
    assert left_out == []


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> Path:
    if named := os.environ.get("MAYA_AUDIT_WHEEL"):
        return Path(named).resolve()
    if importlib.util.find_spec("setuptools") is None:
        pytest.skip("no setuptools here to build a wheel offline; run tools/check_installed_package.py "
                    "or set MAYA_AUDIT_WHEEL")
    return dist.build_wheel(tmp_path_factory.mktemp("build"), isolation=False)


def test_wheel_contains_required_rule_resources(wheel):
    assert dist.missing_resources(wheel) == []


def test_installed_package_resolves_rule_and_action_outside_checkout(wheel, tmp_path):
    smoke = dist.install_and_smoke(wheel, tmp_path)
    assert dist.problems(smoke) == []
    assert smoke["rule"] == "idx6.broken"
    assert smoke["remediation"]["task_id"] == "str2.no_h1"


@pytest.mark.parametrize("content", [None, "", "{not json", '{"actions": {}}', '{"other": 1}'])
def test_missing_required_catalogue_is_explicit_error(content, tmp_path, monkeypatch):
    """A missing, unreadable or empty action catalogue is an installation fault, never "no actions" (DECISIONS 279)."""
    from maya_audit import facts, rules
    if content is not None:
        (tmp_path / "rule_actions.json").write_text(content, encoding="utf-8")
    monkeypatch.setattr(rules, "__file__", str(tmp_path / "rules.py"))
    facts._catalogue.cache_clear()
    try:
        with pytest.raises(rules.EngineDataMissing, match="rule_actions.json"):
            facts.contract({"rule_id": "str2.no_h1", "evidence": {}, "scope": {}})
    finally:
        facts._catalogue.cache_clear()


def test_missing_rule_table_is_explicit_error(tmp_path, monkeypatch):
    from maya_audit import rules
    monkeypatch.setattr(rules, "__file__", str(tmp_path / "rules.py"))
    rules._table.cache_clear()
    try:
        with pytest.raises(rules.EngineDataMissing, match="rule_ids.json is missing"):
            rules.rule_id("STR-2", "The homepage has no <h1>")
    finally:
        rules._table.cache_clear()
