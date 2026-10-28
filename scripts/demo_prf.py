"""Run the full audit against the PRF fake-server scenarios and print the PRF (and IDX-1) results.

    .venv/bin/python scripts/demo_prf.py                   # all runs
    .venv/bin/python scripts/demo_prf.py prf_pagespeed     # PRF-3 against fake PageSpeed Insights and CrUX APIs
    .venv/bin/python scripts/demo_prf.py --json-dir reports

Nothing here touches the internet: every site and API is served from 127.0.0.1.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fakeserver import FakeServer  # noqa: E402
from fakeserver.prf_scenarios import FAST_PRF, PRF_SCENARIOS, crux_api, prf_site, psi_api  # noqa: E402
from fakeserver.scenarios import SCENARIOS  # noqa: E402
from maya_audit.audit import AuditOutcome, run_audit  # noqa: E402
from maya_audit.config import CrawlConfig  # noqa: E402
from maya_audit.report import build_report, render_checks, write_json  # noqa: E402

EXTRA = ("prf_rate_limited", "prf_pagespeed", "prf_pagespeed_verified")


def print_outcome(label: str, description: str, outcome: AuditOutcome, extra: list[str], json_dir: str | None) -> None:
    bar = "=" * 100
    print(bar)
    print(f"SCENARIO {label}: {description}")
    print(bar)
    gates = {g.check_id: g for g in outcome.gates}
    print("INT gates: " + " · ".join(f"{g.check_id} {g.state}" for g in outcome.gates))
    print(f"INT-4: {gates['INT-4'].summary}")
    print()
    print(render_checks(outcome.result, [c for c in outcome.checks if c.check_id.startswith("PRF") or c.check_id == "IDX-1"]))
    for line in extra:
        print(line)
    print()
    if json_dir:
        os.makedirs(json_dir, exist_ok=True)
        path = os.path.join(json_dir, f"{label}.json")
        write_json(build_report(outcome.result, outcome.gates, outcome.checks), path)
        print(f"      evidence JSON: {path}\n")


def server_view(requests) -> list[str]:
    by_path: dict[str, int] = {}
    for r in requests:
        by_path[r.route_path] = by_path.get(r.route_path, 0) + 1
    return ["Server-side view (independent of Maya's own log)",
            f"      GET requests per path: {dict(sorted(by_path.items()))}",
            f"      user agents seen: {sorted({r.user_agent for r in requests})}"]


def run_plain(name: str, json_dir: str | None) -> None:
    scenario = PRF_SCENARIOS[name]
    with FakeServer(scenario.build()) as site:
        options = dict(scenario.config)
        if "key_pages" in options:
            options["key_pages"] = tuple(site.base_url + p for p in options["key_pages"])
        outcome = run_audit(site.base_url + scenario.start_path, CrawlConfig(**options))
        requests = list(site.requests)
    print_outcome(name, scenario.description, outcome, server_view(requests), json_dir)


def run_rate_limited(json_dir: str | None) -> None:
    scenario = SCENARIOS["rate_limited"]
    with FakeServer(scenario.build()) as site:
        outcome = run_audit(site.base_url + "/", CrawlConfig(**{**FAST_PRF, **scenario.config}))
        requests = list(site.requests)
    print_outcome("prf_rate_limited", "The INT rate_limited site: the crawl stops on a long Retry-After, so PRF must "
                  "send no extra requests.", outcome, server_view(requests), json_dir)


def run_pagespeed(json_dir: str | None, verified: bool = False) -> None:
    token = "owner-token" if verified else None
    with FakeServer(prf_site(token)) as site, FakeServer(psi_api()) as psi, \
            FakeServer(crux_api(lambda: site.base_url)) as crux:
        config = CrawlConfig(**{**FAST_PRF, "prf_enabled": False}, key_pages=(site.base_url + "/", site.base_url + "/slow"),
                             pagespeed_enabled=True, google_api_key="psi-test-key-123",
                             psi_endpoint=psi.base_url + "/pagespeedonline/v5/runPagespeed",
                             crux_endpoint=crux.base_url + "/v1/records:queryRecord",
                             site_verification_token=token, probes_enabled=False)
        outcome = run_audit(site.base_url + "/", config)
        psi_requests, crux_requests = len(psi.requests), len(crux.requests)
    extra = [f"      requests to the fake PageSpeed Insights API: {psi_requests}"
             + ("" if verified else " (ownership not verified: must be 0)"),
             f"      requests to the fake CrUX API: {crux_requests}"]
    label = "prf_pagespeed_verified" if verified else "prf_pagespeed"
    what = ("ownership-verified: lab runs (3 per key page, median) plus CrUX field data" if verified else
            "ownership NOT verified: CrUX field data only (URL record for /, origin fallback for /slow), no lab runs")
    print_outcome(label, f"PRF-3 with an API key; {what}.", outcome, extra, json_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="*", default=[*PRF_SCENARIOS, *EXTRA])
    parser.add_argument("--json-dir")
    args = parser.parse_args()
    for name in args.scenarios:
        if name == "prf_rate_limited":
            run_rate_limited(args.json_dir)
        elif name in ("prf_pagespeed", "prf_pagespeed_verified"):
            run_pagespeed(args.json_dir, verified=name.endswith("verified"))
        else:
            run_plain(name, args.json_dir)


if __name__ == "__main__":
    main()
