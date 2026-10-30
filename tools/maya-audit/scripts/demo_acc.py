"""Run the full audit (INT gates + ACC-1..ACC-8) against every ACC fake-server scenario.

    .venv/bin/python scripts/demo_acc.py                 # all scenarios
    .venv/bin/python scripts/demo_acc.py acc_waf_verified
    .venv/bin/python scripts/demo_acc.py --json-dir reports

Nothing here touches the internet: every site is served from 127.0.0.1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fakeserver import FakeServer  # noqa: E402
from fakeserver.acc_scenarios import ACC_SCENARIOS, Scenario  # noqa: E402
from maya_audit.audit import run_audit  # noqa: E402
from maya_audit.config import CrawlConfig  # noqa: E402
from maya_audit.intent import DeclaredPolicy, IntentMarking  # noqa: E402
from maya_audit.registry import REGISTRY  # noqa: E402
from maya_audit.report import build_report, render_checks, write_json  # noqa: E402

BOT_TOKENS = [e.token.lower() for e in REGISTRY]


def sample_logs(directory: str) -> dict:
    """A small combined-format log plus an IP-range file, for the ACC-5 demo."""
    ranges = os.path.join(directory, "searchbot.json")
    with open(ranges, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"prefixes": [{"ipv4Prefix": "20.171.0.0/16"}]}, fh)
    ua = "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot"
    log = os.path.join(directory, "access.log")
    with open(log, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join([
            f'20.171.1.1 - - [10/Sep/2026:10:00:00 +0000] "GET / HTTP/1.1" 200 512 "-" "{ua}"',
            f'20.171.1.2 - - [11/Sep/2026:10:00:00 +0000] "GET /pricing HTTP/1.1" 200 512 "-" "{ua}"',
            f'20.171.1.2 - - [12/Sep/2026:10:00:00 +0000] "GET /pricing HTTP/1.1" 503 12 "-" "{ua}"',
            f'1.2.3.4 - - [12/Sep/2026:11:00:00 +0000] "GET / HTTP/1.1" 200 512 "-" "{ua}"',
        ]))
    return {"access_logs": (log,), "ip_range_files": (("OAI-SearchBot", ranges),)}


EXTRA_RUNS = {
    "acc_robots_rules+policy+marking": (
        "acc_robots_rules",
        {"policy": DeclaredPolicy(training_bots="block"),
         "intent_markings": (IntentMarking("m-pricing", "ACC-2", "disallow", "/pricing", token="OAI-SearchBot",
                                           marked_by="site owner", note="pricing is gated on purpose"),)},
    ),
    "acc_meta_controls+tag_marking": (
        "acc_meta_controls",
        {"intent_markings": (IntentMarking("m-tags", "ACC-3", "noindex", "/tag/*", marked_by="site owner"),)},
    ),
    "acc_ai_friendly+access_logs": ("acc_ai_friendly", "logs"),
}


def run(label: str, scenario: Scenario, overrides: dict, json_dir: str | None) -> None:
    with FakeServer(scenario.build()) as server:
        options = {**scenario.config, **overrides}
        if "key_pages" in options:
            options["key_pages"] = tuple(server.base_url + p for p in options["key_pages"])
        if "intent_markings" in options:
            options["intent_markings"] = tuple(
                replace(m, scope=m.scope.replace("{base}", server.base_url)) for m in options["intent_markings"])
        config = CrawlConfig(**options)
        outcome = run_audit(server.base_url + scenario.start_path, config)
        seen = list(server.requests)

    bar = "=" * 100
    print(bar)
    print(f"SCENARIO {label}: {scenario.description}")
    print(bar)
    print("INT gates: " + " · ".join(f"{g.check_id} {g.state}" for g in outcome.gates))
    print()
    print(render_checks(outcome.result, outcome.checks))
    probe_like = [r for r in seen if any(t in r.user_agent.lower() for t in BOT_TOKENS) or "Chrome/" in r.user_agent]
    tagged = sum(r.headers.get("x-maya-probe") == "ua-differential" for r in probe_like)
    print("Server-side view (independent of Maya's own log)")
    print(f"      requests received: {len(seen)} · first: {seen[0].path if seen else None}")
    print(f"      requests with bot or browser user agents: {len(probe_like)} (tagged X-Maya-Probe: {tagged})")
    if scenario.must_not_request:
        hits = [r.path for r in seen if any(r.path.startswith(f) for f in scenario.must_not_request)]
        print(f"      site forbids {list(scenario.must_not_request)} for Maya → requested anyway: {hits or 'none'}")
    print()
    if json_dir:
        os.makedirs(json_dir, exist_ok=True)
        path = os.path.join(json_dir, f"{label}.json")
        write_json(build_report(outcome.result, outcome.gates, outcome.checks), path)
        print(f"      evidence JSON: {path}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="*", default=[*ACC_SCENARIOS, *EXTRA_RUNS])
    parser.add_argument("--json-dir")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        for label in args.scenarios:
            if label in EXTRA_RUNS:
                base, overrides = EXTRA_RUNS[label]
                overrides = sample_logs(tmp) if overrides == "logs" else overrides
                run(label, ACC_SCENARIOS[base], overrides, args.json_dir)
            else:
                run(label, ACC_SCENARIOS[label], {}, args.json_dir)


if __name__ == "__main__":
    main()
