"""The maya-audit-pro skill's client brief ("Müşteri özeti", DECISIONS 319): at most 5 pages for the business owner,
built by Maya Audit itself (`maya_audit_web/team_report/brief.py`) from the same data as the team report, so the skill
and the web app's "Müşteri özeti (PDF)" print the same brief. This file only finds the engine: `--maya-src`, the
installed package, or the repository holding this skill.

Usage: python brief.py <report.json> --lang tr|en --pdf ozet.pdf [--html ozet.html] [--png DIR] [--review review.json]
"""
import sys
from pathlib import Path


def _engine() -> None:
    args = sys.argv[1:]
    where = [args[args.index("--maya-src") + 1]] if "--maya-src" in args[:-1] else []
    if where:
        i = sys.argv.index("--maya-src")
        del sys.argv[i:i + 2]
    for folder in [*where, str(Path(__file__).resolve().parents[4])]:
        if (Path(folder) / "maya_audit_web" / "team_report" / "brief.py").is_file():
            if folder not in sys.path:
                sys.path.insert(0, str(Path(folder).resolve()))
            return


_engine()
from maya_audit_web.team_report import brief as _impl  # noqa: E402

if __name__ == "__main__":
    sys.exit(_impl.main())
else:
    sys.modules[__name__] = _impl
