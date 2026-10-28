"""Build the wheel, install it outside the checkout, and prove the engine's data files load from it.

Implementation guide stage 01. Before 0.2.9 the wheel left out `maya_audit/rule_ids.json` and
`maya_audit/rule_actions.json`, so an installed (non-editable) package could not resolve a rule id or an action.

    <venv-python> tools/check_installed_package.py              # build, install in a temporary venv, smoke test
    <venv-python> tools/check_installed_package.py --wheel X    # skip the build, check an existing wheel

No website or provider is contacted. Building with build isolation (the default) lets pip fetch the setuptools
backend from the package index; `--no-isolation` uses the setuptools already installed and needs no network.
The installed copy runs with `-I` from a temporary working directory and must not be imported from the checkout.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Files the engine reads at run time that are not Python modules. Every one must be inside the wheel.
REQUIRED = ("maya_audit/rule_ids.json", "maya_audit/rule_actions.json")
# What the build needs and nothing else: never the venv, .env, saved audits or review files.
BUILD_INPUTS = ("pyproject.toml", "README.md", "maya_audit", "maya_audit_web")

# Runs inside the temporary venv. argv[1] is the checkout, which the imported package must not come from.
SMOKE = r'''
import json, pathlib, sys
import maya_audit
from maya_audit import facts, rules
checkout = pathlib.Path(sys.argv[1]).resolve()
module = pathlib.Path(maya_audit.__file__).resolve()
rule = rules.rule_id("IDX-6", "Link target returns 404, linked from 2 page(s): https://example.test/old")
finding = {"rule_id": "str2.no_h1", "evidence": {}, "scope": {}}
facts.contract(finding)
print(json.dumps({"module": str(module), "from_checkout": checkout == module or checkout in module.parents,
                  "version": maya_audit.__version__, "rule": rule,
                  "action_en": (facts._catalogue().get("str2.no_h1") or {}).get("en"),
                  "remediation": finding.get("remediation")}))
'''


def build_wheel(out_dir: Path, *, isolation: bool = True) -> Path:
    """Build the wheel from a copy of the build inputs (the checkout gets no build/ or egg-info)."""
    source = out_dir / "source"
    source.mkdir(parents=True)
    for name in BUILD_INPUTS:
        path = ROOT / name
        if path.is_dir():
            shutil.copytree(path, source / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        elif path.is_file():
            shutil.copy2(path, source / name)
    dist = out_dir / "dist"
    command = [sys.executable, "-m", "pip", "wheel", "--no-deps", "--quiet", "--wheel-dir", str(dist), str(source)]
    if not isolation:
        command[4:4] = ["--no-build-isolation", "--no-index"]
    subprocess.run(command, check=True, cwd=out_dir)
    (wheel,) = dist.glob("maya_audit-*.whl")
    return wheel


def missing_resources(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    return [name for name in REQUIRED if name not in names]


def install_and_smoke(wheel: Path, work: Path) -> dict:
    """Install `wheel` alone (no dependencies, no index) in a new venv under `work`, run SMOKE there."""
    env_dir = work / "venv"
    venv.EnvBuilder(with_pip=True, clear=True).create(env_dir)
    python = env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run([str(python), "-m", "pip", "install", "--no-deps", "--no-index", "--quiet", str(wheel)],
                   check=True, cwd=work)
    run_dir = work / "elsewhere"
    run_dir.mkdir()
    done = subprocess.run([str(python), "-I", "-c", SMOKE, str(ROOT)], cwd=run_dir,
                          capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        last = (done.stderr.strip().splitlines() or ["no error output"])[-1]
        raise RuntimeError(f"the installed package failed the smoke run: {last}")
    return json.loads(done.stdout.strip().splitlines()[-1])


def problems(smoke: dict) -> list[str]:
    found = []
    if smoke.get("from_checkout"):
        found.append(f"imported from the checkout, not the installed package: {smoke.get('module')}")
    if smoke.get("rule") != "idx6.broken":
        found.append(f"rule id not resolved from rule_ids.json: {smoke.get('rule')!r}")
    if not smoke.get("action_en"):
        found.append("action str2.no_h1 not read from rule_actions.json")
    if (smoke.get("remediation") or {}).get("task_id") != "str2.no_h1":
        found.append(f"finding contract has no remediation from the catalogue: {smoke.get('remediation')!r}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wheel", type=Path, help="check this wheel instead of building one")
    parser.add_argument("--no-isolation", action="store_true", help="build with the installed setuptools, offline")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="maya-wheel-") as tmp:
        work = Path(tmp)
        wheel = args.wheel.resolve() if args.wheel else build_wheel(work / "build", isolation=not args.no_isolation)
        print(f"wheel: {wheel.name}")
        if missing := missing_resources(wheel):
            print("FAIL: missing from the wheel: " + ", ".join(missing))
            return 1
        print("wheel contains: " + ", ".join(REQUIRED))
        smoke = install_and_smoke(wheel, work)
        print("installed module: " + smoke["module"])
        print(f"version {smoke['version']}; rule {smoke['rule']}; action str2.no_h1: {smoke['action_en']!r}")
        if found := problems(smoke):
            print("FAIL: " + "; ".join(found))
            return 1
    print("PASS: installed package resolves a rule and an action outside the checkout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
