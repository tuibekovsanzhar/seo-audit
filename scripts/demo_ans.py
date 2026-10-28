"""Run the full audit against the ANS fake site and print the answer-engine panel.

    .venv/bin/python scripts/demo_ans.py                  # citations supplied, zero-citation file, and no file at all
    .venv/bin/python scripts/demo_ans.py --json-dir reports

Nothing here touches the internet: the site is served from 127.0.0.1 and the citation
records come from a local JSON file (the T4 cost is paid upstream, in Maya's pipeline).
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fakeserver import FakeServer  # noqa: E402
from fakeserver.ans_scenarios import ANS_SCENARIOS, FAST_ANS, empty_records, write_citations  # noqa: E402
from maya_audit.audit import AuditOutcome, run_audit  # noqa: E402
from maya_audit.config import CrawlConfig  # noqa: E402
from maya_audit.report import build_report, render_checks, write_json  # noqa: E402

RUNS = {
    "ans_cited_pages": "Citation records supplied: two engines, one off-site URL, two invalid records.",
    "ans_zero_citations": "A citation file with zero records: must read as 0 citations, not as 'no data'.",
    "ans_no_citation_data": "No --citations file at all: the panel must say Not assessed, not 'zero'.",
}


def print_outcome(label: str, description: str, outcome: AuditOutcome, extra: list[str], json_dir: str | None) -> None:
    bar = "=" * 100
    print(bar)
    print(f"RUN {label}: {description}")
    print(bar)
    print("INT gates: " + " · ".join(f"{g.check_id} {g.state}" for g in outcome.gates))
    site = [c for c in outcome.checks if not c.check_id.startswith("ANS")]
    findings = [f for c in site for f in c.findings]
    print(f"Site checks: {len(site)} checks, {len(findings)} findings (unchanged by the panel below)")
    print()
    print(render_checks(outcome.result, [c for c in outcome.checks if c.check_id.startswith("ANS")]))
    for line in extra:
        print(line)
    print()
    if json_dir:
        os.makedirs(json_dir, exist_ok=True)
        path = os.path.join(json_dir, f"{label}.json")
        write_json(build_report(outcome.result, outcome.gates, outcome.checks), path)
        print(f"      evidence JSON: {path}\n")


def run(label: str, json_dir: str | None) -> None:
    scenario = ANS_SCENARIOS["ans_cited_pages"]
    with FakeServer(scenario.build()) as site, tempfile.TemporaryDirectory() as tmp:
        citations = None
        if label == "ans_cited_pages":
            citations = write_citations(tmp, site.base_url)
        elif label == "ans_zero_citations":
            citations = write_citations(tmp, site.base_url, empty_records())
        outcome = run_audit(site.base_url + "/", CrawlConfig(**FAST_ANS, citations_file=citations))
        requests = list(site.requests)
    extra = ["Server-side view (independent of Maya's own log)",
             f"      cited URLs the crawl had not fetched, requested once each: "
             f"{sorted({r.route_path for r in requests if r.route_path in ('/removed',)})}",
             f"      robots-disallowed /internal/ requests received: "
             f"{[r.path for r in requests if r.path.startswith('/internal/')] or 'none'}"]
    print_outcome(label, RUNS[label], outcome, extra, json_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="*", default=list(RUNS))
    parser.add_argument("--json-dir")
    args = parser.parse_args()
    for label in args.runs:
        run(label, args.json_dir)


if __name__ == "__main__":
    main()
