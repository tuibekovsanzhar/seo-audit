"""Run the full audit against the RND fake-server scenarios and print the rendering results.

    .venv/bin/python scripts/demo_rnd.py                 # all runs (rendering needs Playwright + Chromium)
    .venv/bin/python scripts/demo_rnd.py rnd_csr_app
    .venv/bin/python scripts/demo_rnd.py --json-dir reports

Nothing here touches the internet: every site is served from 127.0.0.1.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fakeserver import FakeServer  # noqa: E402
from fakeserver.rnd_scenarios import FAST_RND, RND_SCENARIOS, csr_site, third_party_site  # noqa: E402
from maya_audit.audit import AuditOutcome, run_audit  # noqa: E402
from maya_audit.config import CrawlConfig  # noqa: E402
from maya_audit.report import build_report, render_checks, write_json  # noqa: E402

CSR_FACTS = (("/pricing", "Pro plan $49/mo"), ("/pricing", "Enterprise: contact sales"),
             ("/pricing", "Starter plan $9/mo"), ("/ssr", "Founded in 2012"))


def print_outcome(label: str, description: str, outcome: AuditOutcome, extra: list[str], json_dir: str | None) -> None:
    bar = "=" * 100
    print(bar)
    print(f"SCENARIO {label}: {description}")
    print(bar)
    gates = {g.check_id: g for g in outcome.gates}
    print("INT gates: " + " · ".join(f"{g.check_id} {g.state}" for g in outcome.gates))
    print(f"INT-3: {gates['INT-3'].summary}")
    print(f"INT-4: {gates['INT-4'].summary}")
    for page in gates["INT-3"].evidence["rendered_pages"]:
        print(f"      rendered {page['url']} ok={page['ok']} allowed={page['requests_allowed']} aborted={page['requests_aborted']}")
    print()
    print(render_checks(outcome.result, [c for c in outcome.checks if c.check_id.startswith("RND")]))
    for line in extra:
        print(line)
    print()
    if json_dir:
        os.makedirs(json_dir, exist_ok=True)
        path = os.path.join(json_dir, f"{label}.json")
        write_json(build_report(outcome.result, outcome.gates, outcome.checks), path)
        print(f"      evidence JSON: {path}\n")


def run_csr(json_dir: str | None) -> None:
    with FakeServer(third_party_site()) as third_party, FakeServer(csr_site(lambda: third_party.base_url)) as site:
        config = CrawlConfig(**FAST_RND, render_budget=7, key_pages=(site.base_url + "/pricing",), critical_facts=CSR_FACTS)
        outcome = run_audit(site.base_url + "/", config)
        site_requests, third_party_requests = list(site.requests), list(third_party.requests)
    aborted = [f"      aborted in browser: {r['url']} ({r['reason']})"
               for e in outcome.result.render.pages.values() for r in e.get("requests", []) if r["action"] == "aborted"]
    extra = [
        "Server-side view (independent of Maya's own log)",
        f"      non-GET requests received: {[r.path for r in site_requests if r.method != 'GET'] or 'none'}",
        f"      robots-disallowed /private/ requests received: {[r.path for r in site_requests if r.path.startswith('/private/')] or 'none'}",
        f"      requests received by the third-party origin: {len(third_party_requests)}",
        f"      user agents seen: {sorted({r.user_agent for r in site_requests})}",
        *aborted,
    ]
    print_outcome("rnd_csr_app", "Client-rendered pages, a partially rendered page, a server-rendered page, a third-party "
                  "script, a robots-disallowed script, tabs / load-more / a form / a POST beacon, and a page outside "
                  "the 7-page render budget.", outcome, extra, json_dir)


def run_raw(name: str, json_dir: str | None) -> None:
    scenario = RND_SCENARIOS[name]
    with FakeServer(scenario.build()) as site:
        outcome = run_audit(site.base_url + scenario.start_path, CrawlConfig(**scenario.config))
    print_outcome(name, scenario.description, outcome, [], json_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="*", default=["rnd_csr_app", *RND_SCENARIOS])
    parser.add_argument("--json-dir")
    args = parser.parse_args()
    for name in args.scenarios:
        run_csr(args.json_dir) if name == "rnd_csr_app" else run_raw(name, args.json_dir)


if __name__ == "__main__":
    main()
