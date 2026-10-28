"""Run the full audit against every IDX fake-server scenario and print the IDX results.

    .venv/bin/python scripts/demo_idx.py                 # all scenarios, TLS cases, and the Google/Bing APIs
    .venv/bin/python scripts/demo_idx.py idx_canonicals
    .venv/bin/python scripts/demo_idx.py --json-dir reports

Nothing here touches the internet: every site and API is served from 127.0.0.1 / localhost.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fakeserver import FakeServer  # noqa: E402
from fakeserver.idx_scenarios import IDX_SCENARIOS, bing_api, gsc_api, tls_sites  # noqa: E402
from maya_audit.audit import AuditOutcome, run_audit  # noqa: E402
from maya_audit.config import CrawlConfig  # noqa: E402
from maya_audit.report import build_report, render_checks, write_json  # noqa: E402

TLS_RUNS = {
    "idx_tls_valid": ("valid", True),
    "idx_tls_near_expiry": ("near_expiry", True),
    "idx_tls_expired": ("expired", True),
    "idx_tls_hostname_mismatch": ("mismatch", True),
    "idx_tls_no_http_redirect": ("valid", False),
}


def print_outcome(label: str, description: str, outcome: AuditOutcome, json_dir: str | None) -> None:
    bar = "=" * 100
    print(bar)
    print(f"SCENARIO {label}: {description}")
    print(bar)
    print("INT gates: " + " · ".join(f"{g.check_id} {g.state}" for g in outcome.gates))
    print("ACC: " + " · ".join(f"{c.check_id} {c.status}" for c in outcome.checks if c.check_id.startswith("ACC")))
    print()
    print(render_checks(outcome.result, [c for c in outcome.checks if c.check_id.startswith("IDX")]))
    if json_dir:
        os.makedirs(json_dir, exist_ok=True)
        path = os.path.join(json_dir, f"{label}.json")
        write_json(build_report(outcome.result, outcome.gates, outcome.checks), path)
        print(f"      evidence JSON: {path}\n")


def run_scenario(name: str, json_dir: str | None) -> None:
    scenario = IDX_SCENARIOS[name]
    with FakeServer(scenario.build()) as site:
        options = dict(scenario.config)
        if "key_pages" in options:
            options["key_pages"] = tuple(site.base_url + p for p in options["key_pages"])
        if name == "idx_gsc_bing":
            with FakeServer(gsc_api(lambda: site.base_url)) as gsc, FakeServer(bing_api(lambda: site.base_url)) as bing:
                config = CrawlConfig(
                    **options, gsc_access_token="test-token", gsc_site_url=site.base_url + "/",
                    gsc_endpoint=gsc.base_url + "/v1/urlInspection/index:inspect",
                    bing_api_key="bing-key", bing_site_url=site.base_url + "/",
                    bing_endpoint=bing.base_url + "/webmaster/api.svc/json", indexnow_key="wrongkey123",
                )
                outcome = run_audit(site.base_url + scenario.start_path, config)
        else:
            outcome = run_audit(site.base_url + scenario.start_path, CrawlConfig(**options))
    print_outcome(name, scenario.description, outcome, json_dir)


def run_tls(name: str, json_dir: str | None) -> None:
    kind, redirect = TLS_RUNS[name]
    with tls_sites(kind, redirect) as (https, http, ca_bundle):
        config = CrawlConfig(request_delay_s=0, robots_sample_interval_s=0.05, refetch_delay_s=0, prf_round_gap_s=0,
                             ca_bundle=ca_bundle, http_port=http.port, render_enabled=False)
        outcome = run_audit(https.base_url + "/", config)
    print_outcome(name, f"HTTPS site with a {kind.replace('_', ' ')} certificate; "
                        f"plain HTTP {'redirects' if redirect else 'does not redirect'} to HTTPS.", outcome, json_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="*", default=[*IDX_SCENARIOS, *TLS_RUNS])
    parser.add_argument("--json-dir")
    args = parser.parse_args()
    for name in args.scenarios:
        (run_tls if name in TLS_RUNS else run_scenario)(name, args.json_dir)


if __name__ == "__main__":
    main()
