"""Run the INT gates against every fake-server scenario and print the reports.

    .venv/bin/python scripts/demo_int.py              # all scenarios
    .venv/bin/python scripts/demo_int.py healthy      # one scenario
    .venv/bin/python scripts/demo_int.py --json-dir reports

Nothing here touches the internet: every site is served from 127.0.0.1.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fakeserver import SCENARIOS, FakeServer  # noqa: E402
from maya_audit.checks.integrity import run_integrity_gates  # noqa: E402
from maya_audit.config import CrawlConfig  # noqa: E402
from maya_audit.crawler import Crawler  # noqa: E402
from maya_audit.report import build_report, render_text, write_json  # noqa: E402


def run(name: str, json_dir: str | None) -> None:
    scenario = SCENARIOS[name]
    with FakeServer(scenario.build()) as server:
        overrides = dict(scenario.config)
        if "key_pages" in overrides:
            overrides["key_pages"] = tuple(server.base_url + p for p in overrides["key_pages"])
        config = CrawlConfig(**overrides)
        result = Crawler(config).run(server.base_url + scenario.start_path)
        gates = run_integrity_gates(result, config)
        seen = server.paths()

    bar = "=" * 100
    print(bar)
    print(f"SCENARIO {name}: {scenario.description}")
    print(bar)
    print(render_text(result, gates))
    forbidden_hits = [p for p in seen if any(p.startswith(f) for f in scenario.must_not_request)]
    print("Server-side view (independent of Maya's own log)")
    print(f"      requests received: {len(seen)} · first request: {seen[0] if seen else None}")
    print(f"      paths: {seen}")
    if scenario.must_not_request:
        print(f"      site forbids {list(scenario.must_not_request)} → requested anyway: {forbidden_hits or 'none'}")
    print()
    if json_dir:
        os.makedirs(json_dir, exist_ok=True)
        path = os.path.join(json_dir, f"{name}.json")
        write_json(build_report(result, gates), path)
        print(f"      evidence JSON: {path}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="*", default=list(SCENARIOS))
    parser.add_argument("--json-dir")
    args = parser.parse_args()
    for name in args.scenarios:
        run(name, args.json_dir)


if __name__ == "__main__":
    main()
