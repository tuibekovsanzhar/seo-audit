"""The finding catalogue for the SEO team (DECISIONS 353).

  python scripts/finding_catalogue.py export OUT.xlsx [--home ~/.maya-audit/web]
      Every finding, card and checklist item the engine can produce, with its Turkish texts, and how many saved audits
      under --home triggered it (read only; no home: counts are 0/0).
  python scripts/finding_catalogue.py import EDITED.xlsx [--dry-run] [--report diff.md]
      Writes the "Yeni …" texts back into the data files after checking placeholders, digits, lengths and step counts;
      a row that fails is refused and listed. --dry-run writes nothing. The diff report is printed (and saved).
No network, no provider.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    from maya_audit_web import finding_catalogue as fc
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("export")
    ex.add_argument("out")
    ex.add_argument("--home", default=None, help="a web home whose saved audits are counted (read only)")
    im = sub.add_parser("import")
    im.add_argument("xlsx")
    im.add_argument("--dry-run", action="store_true")
    im.add_argument("--report", default=None, help="also save the diff report here")
    a = ap.parse_args(argv)
    if a.command == "export":
        counts = fc.export(Path(a.out), Path(a.home).expanduser() if a.home else None)
        print(f"{a.out}: {counts['rows']} satır; {counts['rules']} kural; türler {counts['kinds']}; "
              f"{counts['audits']} kayıtlı denetim okundu; {counts['triggered']} kural en az bir denetimde çıktı")
        return 0
    try:
        edits = fc.read_edits(Path(a.xlsx))
    except fc.CatalogueError as exc:
        print(f"HATA: {exc}")
        return 2
    changes, refused, notes = fc.plan(edits)
    written = [] if a.dry_run else fc.apply(changes)
    text = fc.diff_report(changes, refused, notes, applied=not a.dry_run)
    if a.report:
        Path(a.report).write_text(text, encoding="utf-8")
    print(text)
    if written:
        print("Yazılan dosyalar: " + ", ".join(written))
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
