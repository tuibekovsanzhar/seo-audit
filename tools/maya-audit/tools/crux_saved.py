"""Ask Google again for a saved audit's Core Web Vitals (DECISIONS 334): no crawl, the website is not requested.

    .venv/bin/python tools/crux_saved.py <audit folder | its artifacts folder | report.json>

The Chrome UX Report is free and its site-level figures are live (the last 28 days), so a saved audit can get them
afterwards. Asks the origin the site landed on, then the typed one, and the homepage's own record; writes
`artifacts/crux.json` beside report.json (which is never written). The web app's results, the team report, the client
brief and the Sektör audit read it. The key is MAYA_AUDIT_CRUX_API_KEY (else MAYA_AUDIT_GOOGLE_API_KEY), from the
environment or .env; it is never printed. The same as "Google'dan yeniden al" in the web app's results.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from maya_audit import crux  # noqa: E402


def folder_of(arg: str) -> Path:
    path = Path(arg).expanduser().resolve()
    if path.name == "report.json":
        return path.parent
    if (path / "artifacts" / "report.json").is_file():
        return path / "artifacts"
    return path


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    folder = folder_of(args[0])
    if not (folder / "report.json").is_file():
        print(f"error: no report.json in {folder}", file=sys.stderr)
        return 2
    key = crux.load_key()
    if not key:
        print("error: no Google key (MAYA_AUDIT_CRUX_API_KEY or MAYA_AUDIT_GOOGLE_API_KEY)", file=sys.stderr)
        return 2
    section = crux.refresh_saved(folder, key)
    asked = ", ".join(f"{a.get('origin') or a.get('url')}: {a.get('http_status')}" for a in section.get("attempts") or [])
    print(f"{section['status']} ({section.get('origin') or '—'}); asked {asked}")
    print(section["summary"])
    print(f"written: {folder / crux.SAVED_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
