"""Write RELEASE-SNAPSHOT.json and CHECKPOINT-VERIFICATION.md for the current source state (DECISIONS 283 (7)).

Both name the application version from `maya_audit.__version__`, the schema from `maya_audit/schema.py` and the
release label given here (for example `w14`). The snapshot's file list is the tracked files `git archive` would ship:
anything marked `export-ignore` in .gitattributes, and every path under `EXCLUDED`, is left out. Writes no archive.

    .venv/bin/python tools/release_metadata.py --release w14
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Never in a release archive: real-site benchmark data, owner reviews, secrets, local Claude configuration.
EXCLUDED = ("benchmarks/real-sites/", "reviews/", ".env", ".claude/")
GENERATED = ("RELEASE-SNAPSHOT.json", "CHECKPOINT-VERIFICATION.md")


def excluded(path: str) -> bool:
    """A path under an excluded folder, or a .env file (the tracked `.env.example` template is not one)."""
    if path == ".env" or (path.startswith(".env.") and path != ".env.example"):
        return True
    return any(path.startswith(p) for p in EXCLUDED if p.endswith("/"))


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def shipped_files() -> list[str]:
    tracked = [p for p in git("ls-files", "-z").split("\0") if p]
    attrs = git("check-attr", "-z", "export-ignore", "--", *tracked).split("\0") if tracked else []
    ignored = {attrs[i] for i in range(0, len(attrs) - 2, 3) if attrs[i + 2] == "set"}
    return sorted(p for p in tracked if p not in ignored and not excluded(p) and p not in GENERATED)


def versions() -> tuple[str, str]:
    sys.path.insert(0, str(ROOT))
    from maya_audit import __version__
    from maya_audit.schema import SCHEMA_VERSION
    return __version__, SCHEMA_VERSION


def snapshot(release: str) -> dict:
    app, schema = versions()
    files = shipped_files()
    return {
        "release": release, "application_version": app, "schema_version": schema,
        "base_commit": git("rev-parse", "HEAD").strip(), "branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
        "source_state": "git HEAD named in base_commit; the files below are the tracked files without export-ignore, "
                        "hashed from the working tree when this file was written",
        "excluded_paths": list(EXCLUDED), "packaging_generated_files": list(GENERATED),
        "files": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files},
    }


def checkpoint(release: str) -> str:
    app, schema = versions()
    return (f"# Checkpoint verification\n\n"
            f"Release {release} / application {app} / schema {schema}. Testable build, not client-delivery approval.\n\n"
            f"Test results for this source state are in `docs/IMPLEMENTATION-STATUS.md`, with each command and its "
            f"result line. Do not infer PASS from this file; a run that is not recorded there was not run.\n\n"
            f"The archive leaves out {', '.join(EXCLUDED)} (see `RELEASE-SNAPSHOT.json` `excluded_paths` and "
            f"`.gitattributes`). No paid calls or live audits are part of this checkpoint.\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release", required=True, help="release label, e.g. w14")
    a = ap.parse_args()
    (ROOT / "RELEASE-SNAPSHOT.json").write_text(json.dumps(snapshot(a.release), indent=2) + "\n", encoding="utf-8")
    (ROOT / "CHECKPOINT-VERIFICATION.md").write_text(checkpoint(a.release), encoding="utf-8")
    print(f"Wrote RELEASE-SNAPSHOT.json and CHECKPOINT-VERIFICATION.md for {a.release}")


if __name__ == "__main__":
    main()
