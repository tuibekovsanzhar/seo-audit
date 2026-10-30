"""Run the full audit against the STR fake-server scenarios and print the STR results.

    .venv/bin/python scripts/demo_str.py                         # all scenarios
    .venv/bin/python scripts/demo_str.py str_entity_links        # the two-origin run, external link checks off
    .venv/bin/python scripts/demo_str.py str_entity_links_external
    .venv/bin/python scripts/demo_str.py --json-dir reports

Nothing here touches the internet: every site is served from 127.0.0.1.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fakeserver import FakeServer  # noqa: E402
from fakeserver.str_scenarios import FAST_STR, STR_SCENARIOS, entity_site, external_site  # noqa: E402
from maya_audit.audit import AuditOutcome, run_audit  # noqa: E402
from maya_audit.config import CrawlConfig  # noqa: E402
from maya_audit.report import build_report, render_checks, write_json  # noqa: E402

ENTITY_RUNS = {
    "str_entity_links": False,
    "str_entity_links_external": True,
}


def print_outcome(label: str, description: str, outcome: AuditOutcome, extra: list[str], json_dir: str | None) -> None:
    bar = "=" * 100
    print(bar)
    print(f"SCENARIO {label}: {description}")
    print(bar)
    gates = {g.check_id: g for g in outcome.gates}
    print("INT gates: " + " · ".join(f"{g.check_id} {g.state}" for g in outcome.gates))
    print(f"INT-4: {gates['INT-4'].summary}")
    print()
    print(render_checks(outcome.result, [c for c in outcome.checks if c.check_id.startswith("STR")]))
    for line in extra:
        print(line)
    print()
    if json_dir:
        os.makedirs(json_dir, exist_ok=True)
        path = os.path.join(json_dir, f"{label}.json")
        write_json(build_report(outcome.result, outcome.gates, outcome.checks), path)
        print(f"      evidence JSON: {path}\n")


def run_entity(label: str, external: bool, json_dir: str | None):
    with FakeServer(external_site(lambda: site.base_url)) as ext, FakeServer(entity_site(lambda: ext.base_url)) as site:
        config = CrawlConfig(**FAST_STR, check_external_links=external)
        outcome = run_audit(site.base_url + "/", config)
        site_requests, ext_requests = list(site.requests), list(ext.requests)
    extra = [
        "Server-side view (independent of Maya's own log)",
        f"      requests received by the OTHER origin: {[r.path for r in ext_requests] or 'none'}",
        f"      robots-disallowed /private/ requests received by the site: "
        f"{[r.path for r in site_requests if r.path.startswith('/private/')] or 'none'}",
        f"      user agents seen (both origins): {sorted({r.user_agent for r in site_requests + ext_requests})}",
    ]
    description = ("Brand name variants, sameAs links (live, 404, robots-blocked), og:image on another origin, hreflang "
                   "with a one-way link, a 404 target, a robots-disallowed target, a target on another origin, and a "
                   f"Turkish page declared as English. External link checks {'ON' if external else 'OFF (default)'}.")
    print_outcome(label, description, outcome, extra, json_dir)
    return outcome, site_requests, ext_requests


def run_plain(name: str, json_dir: str | None) -> None:
    scenario = STR_SCENARIOS[name]
    with FakeServer(scenario.build()) as site:
        outcome = run_audit(site.base_url + scenario.start_path, CrawlConfig(**scenario.config))
    print_outcome(name, scenario.description, outcome, [], json_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="*", default=[*STR_SCENARIOS, *ENTITY_RUNS])
    parser.add_argument("--json-dir")
    args = parser.parse_args()
    for name in args.scenarios:
        if name in ENTITY_RUNS:
            run_entity(name, ENTITY_RUNS[name], args.json_dir)
        else:
            run_plain(name, args.json_dir)


if __name__ == "__main__":
    main()
