"""The maya-audit-pro skill's `validate_data` step. The template, the text library and the checks live in Maya Audit itself
(`maya_audit_web/team_report/validate_data.py`, DECISIONS 307), so this skill and the web app's "Ekip raporu" render the same
report. This file only finds the engine: `--maya-src`, the installed package, or the repository holding this skill.

Usage: the same arguments as before (`python validate_data.py --help`).
"""
import sys
from pathlib import Path


def _engine() -> None:
    args = sys.argv[1:]
    where = [args[args.index("--maya-src") + 1]] if "--maya-src" in args[:-1] else []
    for folder in [*where, str(Path(__file__).resolve().parents[4])]:
        if (Path(folder) / "maya_audit_web" / "team_report" / "validate_data.py").is_file():
            if folder not in sys.path:
                sys.path.insert(0, str(Path(folder).resolve()))
            return


_engine()
from maya_audit_web.team_report import validate_data as _impl  # noqa: E402

if __name__ == "__main__":
    _impl.main()
else:  # `import validate_data` (the skill's tests) gets the shared module itself
    sys.modules[__name__] = _impl
