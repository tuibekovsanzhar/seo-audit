"""Apply rules changed since a report was written to a saved report, offline (DECISIONS 285).

    .venv/bin/python tools/reassess_saved.py <artifacts/report.json> --out <folder>

Reads report.json and affected-urls.json beside it, writes both re-assessed into --out, with the changes in
`generation.analysis`. The source is never written; --out may not be inside a Maya Audit home (the web app's saved
history). No request is made: sockets are refused for the whole run.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _no_network(*args, **kwargs):
    raise RuntimeError("reassess_saved makes no network request")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    saved = socket.socket.connect, socket.create_connection, socket.getaddrinfo
    socket.socket.connect = _no_network  # type: ignore[method-assign]
    socket.create_connection = _no_network  # type: ignore[assignment]
    socket.getaddrinfo = _no_network  # type: ignore[assignment]
    try:
        return _run(a)
    finally:  # refused for this run only (a caller in the same process gets its sockets back)
        socket.socket.connect, socket.create_connection, socket.getaddrinfo = saved


def _run(a) -> int:
    source, out = a.report.resolve(), a.out.resolve()
    homes = [Path.home() / ".maya-audit"]
    if any(out == h or h in out.parents for h in homes) or out == source.parent:
        raise SystemExit("--out must be a new folder outside the Maya Audit home; the source is never written")
    sys.path.insert(0, str(ROOT))
    from maya_audit.reassess_rules import apply
    report = json.loads(source.read_text(encoding="utf-8"))
    affected_path = source.with_name("affected-urls.json")
    affected = json.loads(affected_path.read_text(encoding="utf-8")) if affected_path.exists() else None
    audit_id = source.parent.parent.name if source.parent.name == "artifacts" else None
    new, aff, record = apply(report, affected, source_audit_id=audit_id)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
    if affected is not None:
        (out / "affected-urls.json").write_text(json.dumps(aff, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"out": str(out), "gate": new["release_gate"].get("decision"), **record}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
