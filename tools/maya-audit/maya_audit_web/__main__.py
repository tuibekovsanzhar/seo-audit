"""Start the local web app:  python -m maya_audit_web [--demo] [--port 8770]

The server listens on 127.0.0.1 only. There is no option to listen anywhere else.
"""

from __future__ import annotations

import argparse
import socket
import sys

HOST = "127.0.0.1"


def build(demo_mode: bool, port: int):
    from . import demo
    from .app import create_app
    from .runner import Engine
    from .store import data_home

    home = data_home()
    if demo_mode:
        from maya_audit import ownership

        ownership.TRANSPORT = demo.NO_DNS_RECORDS  # demo sites are made up: no real DNS lookup about them
        folder = home / "demo"
        citations = str(demo.write_citations(folder))
        engine = Engine(paid=demo.paid_services(folder / "paid"), firecrawl=demo.firecrawl_services(folder / "firecrawl"),
                        transport_factory=demo.site_transport,
                        allow_loopback=True, overrides=demo.OVERRIDES, demo=True,
                        crux_key=lambda: "demo-made-up-key", crux_transport=demo.CRUX_TRANSPORT, archives_transport=demo.ARCHIVES_TRANSPORT,
                        overrides_for=lambda url: {"citations_file": citations} if demo.SHOP in url else {})
    else:
        folder, engine = home, Engine()
    # Revised analyses live under the data home, never beside the installed code (site-packages after a pip install, D-25).
    analyses = None if demo_mode else home / 'analyses'
    # DECISIONS 310: the team works in Turkish; the language switch still offers English.
    return create_app(folder, engine=engine, port=port, analysis_folder=analyses, default_language="tr"), folder


def probe_options(probe: socket.socket, platform: str | None = None) -> None:
    """Make the port probe as strict as the server's own bind (D-17). On Windows SO_REUSEADDR lets a socket bind to a
    port another socket holds, so the probe would say "free" for a busy port: there the probe asks for exclusive use
    instead. Elsewhere SO_REUSEADDR only ignores a port left in TIME_WAIT, as uvicorn does."""
    if (platform or sys.platform) == "win32":
        probe.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", -5), 1)
    else:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m maya_audit_web", description="Maya Audit local web app")
    parser.add_argument("--port", type=int, default=8770, help="local port (default 8770)")
    parser.add_argument("--demo", action="store_true",
                        help="use made-up sites and made-up backlink figures held in memory: no real website is "
                             "contacted and nothing is charged")
    args = parser.parse_args(argv)
    try:
        import uvicorn
    except ImportError:
        print('The web app is not installed yet. From the project folder run:\n'
              '  .venv/bin/pip install -e ".[team]"', file=sys.stderr)
        return 2
    # Say plainly what is wrong before starting anything, instead of a page of error text.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe_options(probe)
        probe.bind((HOST, args.port))
    except OSError:
        print(f"Port {args.port} is already in use on this computer. Either Maya Audit is already running (look for its "
              f"Terminal window), or another program has the port.\nTry another port:\n"
              f"  .venv/bin/python -m maya_audit_web{' --demo' if args.demo else ''} --port {args.port + 1}", file=sys.stderr)
        return 2
    finally:
        probe.close()
    from .runner import WorkerAlreadyRunning
    try:
        app, folder = build(args.demo, args.port)
    except WorkerAlreadyRunning:
        print("Maya Audit is already running on this computer (in another Terminal window). Use that one, or stop it "
              "there with Ctrl+C first.", file=sys.stderr)
        return 2
    print(f"Maya Audit {'DEMO (made-up data, nothing real is contacted)' if args.demo else ''}".rstrip())
    print(f"  Open:    http://{HOST}:{args.port}")
    print(f"  History: {folder}")
    print("  Stop:    Ctrl+C (running audits are stopped politely and can be resumed)")
    uvicorn.run(app, host=HOST, port=args.port, log_level="warning", server_header=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
