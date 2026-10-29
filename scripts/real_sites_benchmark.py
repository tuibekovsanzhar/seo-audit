"""Opt-in real-site benchmark. No provider clients or owner storage are used.

    .venv/bin/python -m scripts.real_sites_benchmark collect --live
    .venv/bin/python -m scripts.real_sites_benchmark score RUN_DIRECTORY
    .venv/bin/python -m scripts.real_sites_benchmark replay RUN_DIRECTORY

expected.yaml files use JSON syntax, a YAML 1.2 subset, so no parser dependency is needed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "real-sites"


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_sites(corpus=CORPUS):
    manifest = read(corpus / "sites.json")
    sites = []
    for site in manifest["sites"]:
        labels = read(corpus / site["id"] / "expected.yaml")
        if labels.get("site") != site["id"]:
            raise ValueError("Expectation identity mismatch: " + site["id"])
        for group in ("must_find", "must_not_find"):
            for row in labels[group]:
                if not row.get("id") or not row.get("check_id") or not row.get("reason"):
                    raise ValueError("Incomplete assertion in " + site["id"])
                if row.get("status") == "verified":
                    proof = row.get("verification") or {}
                    if not all(proof.get(k) for k in ("reviewer", "observed_at", "evidence_sha256", "evidence_reference", "observation")):
                        raise ValueError("Golden label lacks independent evidence: " + row["id"])
                    if not row.get("urls"):
                        raise ValueError("Golden label must define assessed URLs: " + row["id"])
        sites.append({**site, "expectations": labels})
    return sites


def findings(report):
    return [f for c in report.get("checks", []) for f in c.get("findings", [])]


def membership(finding, report):
    scope = finding.get("scope") or {}
    all_urls = (report.get("affected_urls") or {}).get(finding.get("id"))
    return set(all_urls if all_urls is not None else scope.get("_all_urls") or scope.get("urls") or [])


def matches(finding, label, report):
    if finding.get("check_id") != label["check_id"]:
        return False
    if label.get("severity") and finding.get("severity") != label["severity"]:
        return False
    if label.get("severities") and finding.get("severity") not in label["severities"]:
        return False
    if label.get("title_contains") and label["title_contains"].casefold() not in finding.get("title", "").casefold():
        return False
    if label.get("urls") and not set(label["urls"]).intersection(membership(finding, report)):
        return False
    # A machine-match selector identifies a conclusion, never establishes its truth.
    return True


def assessed(report, label):
    check = next((c for c in report.get("checks", []) if c["check_id"] == label["check_id"]), None)
    if not check or check.get("status") in ("not_assessed", "not_applicable"):
        return False
    # A negative requires all labelled URLs to have been read for content checks, or
    # explicitly represented in the check's evidence for request/sitemap checks.
    pages = (report.get("crawl") or {}).get("pages") or []
    read_urls = {p["url"] for p in pages if p.get("content_checks_eligible") is True
                 and p.get("analysis") and not p["analysis"].get("empty_response") and p.get("body_bytes", 0) > 0}
    gaps = (check.get("coverage") or {}).get("not_assessed") or []
    if check.get("status") == "partial" and not gaps:
        return False  # unknown reason for partial assessment
    for gap in gaps:
        if gap.get("part") == "pages found but not read" and set(label.get("urls") or []).issubset(read_urls):
            continue  # a read-page assertion does not claim anything about the unread site
        if label["check_id"] == "STR-12" and gap.get("part") == "content language of pages":
            ev = check.get("evidence") or {}
            unknown = ev.get("language_not_assessed") or []
            total = ev.get("language_not_assessed_count")
            if isinstance(total, int) and total == len(unknown) and not set(label.get("urls") or []).intersection(
                    row.get("url") for row in unknown):
                continue
        return False
    evidence = json.dumps(check.get("evidence") or {}, ensure_ascii=False)
    return bool(label.get("urls")) and all(u in read_urls or (
        label["check_id"].startswith(("IDX-", "ACC-")) and json.dumps(u, ensure_ascii=False) in evidence
    ) for u in label["urls"])


def score(report, expectations):
    rows = []
    used = set()
    items = findings(report)
    for group in ("must_find", "must_not_find"):
        for label in expectations[group]:
            selected = [f for f in items if matches(f, label, report)]
            used.update(f.get("id") for f in selected)
            proof = label.get("verification") or {}
            pinned = proof.get("collection_digest")
            collection = ((report.get("benchmark") or {}).get("collection_digest"))
            if label.get("status") != "verified":
                result = "provisional"
            elif not pinned or pinned != collection:
                result = "unassessed"
            elif group == "must_find" and selected:
                result = "hit"
            elif group == "must_not_find" and selected:
                result = "false_alarm"
            elif not assessed(report, label):
                result = "unassessed"
            else:
                result = "miss" if group == "must_find" else "correct_negative"
            rows.append({"id": label["id"], "expected": group, "result": result,
                         "finding_ids": [f["id"] for f in selected]})
    return {"counts": dict(Counter(r["result"] for r in rows)), "assertions": rows,
            "unlabelled_findings": len([f for f in items if f.get("id") not in used])}


def request_key(request):
    return json.dumps([request.method, str(request.url), request.headers.get("user-agent", ""),
                       request.headers.get("accept", ""), request.headers.get("range", ""),
                       bool(request.headers.get("cookie"))], ensure_ascii=False)


def recording_transport(folder):
    """Tee the engine's existing guarded stream; never read beyond what it requests.

    Credentials, cookies and arbitrary response headers are not retained. Bodies remain
    local ignored benchmark evidence, not committed fixtures or client reports.
    """
    import httpx
    from maya_audit.network import PublicTransport
    allowed_headers = {"content-type", "content-encoding", "location", "last-modified", "etag",
                       "x-robots-tag", "retry-after", "content-length"}
    folder.mkdir()
    records, lock = [], threading.Lock()

    class Stream(httpx.SyncByteStream):
        def __init__(self, stream, row):
            self.stream, self.row, self.parts, self.size = stream, row, [], 0

        def __iter__(self):
            for data in self.stream:
                self.parts.append(data)
                self.size += len(data)
                if self.size > 16 * 1024 * 1024:
                    self.row["capture_truncated"] = True
                    self.parts.pop()
                yield data
            self.row["stream_complete"] = True

        def close(self):
            try:
                self.stream.close()
            finally:
                path = folder / (self.row["id"] + ".body")
                path.write_bytes(b"".join(self.parts))
                self.row["body_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                write(folder / (self.row["id"] + ".record.json"), self.row)

    class Recorder(httpx.BaseTransport):
        def __init__(self):
            self.inner = PublicTransport(allow_loopback=False)

        def handle_request(self, request):
            with lock:
                row = {"id": f"{len(records):06d}", "request_key": request_key(request),
                       "url": str(request.url), "method": request.method, "observed_at": stamp(),
                       "client": request.headers.get("user-agent", "")}
                records.append(row)
                write(folder / (row["id"] + ".record.json"), row)
            try:
                response = self.inner.handle_request(request)
                row.update(status=response.status_code,
                           headers={k: v for k, v in response.headers.items() if k in allowed_headers})
                response.stream = Stream(response.stream, row)
                return response
            except httpx.TransportError as exc:
                row["error_type"] = type(exc).__name__
                write(folder / (row["id"] + ".record.json"), row)
                raise

        def close(self):
            self.inner.close()

    return Recorder(), records


def frozen_transport(folder, records, gaps):
    import httpx
    by_key = defaultdict(list)
    for row in records:
        by_key[row["request_key"]].append(row)
    lock = threading.Lock()

    def respond(request):
        key = request_key(request)
        with lock:
            queue = by_key.get(key)
            row = queue.pop(0) if queue else None
        if row is None:
            gaps.append({"url": str(request.url), "method": request.method, "reason": "no frozen request evidence"})
            raise httpx.ConnectError("Benchmark: request absent from frozen evidence", request=request)
        if row.get("error_type"):
            raise httpx.ConnectError("Benchmark: recorded transport failure " + row["error_type"], request=request)
        path = folder / (row["id"] + ".body")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row["body_sha256"]:
            raise ValueError("Frozen response changed: " + row["id"])
        if not row.get("stream_complete") or row.get("capture_truncated"):
            gaps.append({"url": row["url"], "reason": "source response stream incomplete"})
            raise httpx.ConnectError("Benchmark: incomplete frozen stream", request=request)
        return httpx.Response(row["status"], headers=row["headers"], content=data)

    return httpx.MockTransport(respond)


@contextmanager
def offline_network():
    """Replay workers may consume fixtures, never resolve or connect to a host."""
    connect, resolve = socket.socket.connect, socket.getaddrinfo

    def refused(*args, **kwargs):
        raise RuntimeError("Offline benchmark replay prohibits network/DNS")

    socket.socket.connect, socket.getaddrinfo = refused, refused
    try:
        yield
    finally:
        socket.socket.connect, socket.getaddrinfo = connect, resolve


def source_state():
    files = {}
    for name in ("maya_audit", "maya_audit_web"):
        for path in sorted((ROOT / name).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                files[path.relative_to(ROOT).as_posix()] =hashlib.sha256(path.read_bytes()).hexdigest()
    head_path = ROOT / ".git" / "HEAD"
    manifest = ROOT / "RELEASE-SNAPSHOT.json"
    head = head_path.read_text().strip() if head_path.is_file() else (
        read(manifest).get("base_commit", "unavailable") if manifest.is_file() else "unavailable")
    if head.startswith("ref: "):
        ref = head[5:]
        ref_path = ROOT / ".git" / ref
        head = ref_path.read_text().strip() if ref_path.is_file() else "unavailable"
    runner = ROOT / "scripts" / "real_sites_benchmark.py"
    return {"base_commit": head,
            "base_commit_note": "Reference identity only; files below identify the actual working-tree source",
            "files": files, "source_digest": digest(files),
            "benchmark_runner_sha256": hashlib.sha256(runner.read_bytes()).hexdigest()}


def quick_config(site):
    from maya_audit.config import (CrawlConfig, FAST_RENDER_BUDGET, FAST_SITEMAP_CHECK_MAX,
                                   FAST_LLMS_LINK_CHECKS_MAX, FAST_IMAGE_CHECKS_MAX,
                                   FAST_KEY_IMAGE_CHECKS_MAX, FAST_EXTERNAL_LINK_CHECKS_MAX)
    return CrawlConfig(max_pages=50, time_limit_s=720, block_loopback=True, fast_check=True,
                       render_budget=FAST_RENDER_BUDGET, sitemap_check_max=FAST_SITEMAP_CHECK_MAX,
                       llms_link_checks_max=FAST_LLMS_LINK_CHECKS_MAX, image_checks_max=FAST_IMAGE_CHECKS_MAX,
                       key_image_checks_max=FAST_KEY_IMAGE_CHECKS_MAX,
                       external_link_checks_max=FAST_EXTERNAL_LINK_CHECKS_MAX,
                       allowed_live_hosts=frozenset(site.get("allowed_hosts", [])))


def site_worker(site, folder, replay=None):
    from maya_audit.audit import run_audit
    from maya_audit.report import build_report, affected_urls
    from maya_audit.progress import Hooks
    folder.mkdir()
    begin = time.monotonic()
    events = []
    cfg = quick_config(site)
    if replay:
        # Rendering/OS TLS checks cannot be replayed from HTTP bytes. Do not pretend
        # to have rerun them or permit a browser to fetch fresh site content.
        from dataclasses import replace
        cfg = replace(cfg, render_enabled=False)
        records = read(replay / "requests.json")
        gaps = []
        transport = frozen_transport(replay / "responses", records, gaps)
    else:
        transport, records = recording_transport(folder / "responses")
        gaps = []
    try:
        with offline_network() if replay else nullcontext():
            result = run_audit(site["url"], cfg, transport=transport, hooks=Hooks(on_progress=events.append))
        report = build_report(result.result, result.gates, result.checks)
        report["affected_urls"] = affected_urls(result.checks)
        collection_digest = read(replay / "collection.json")["digest"] if replay else digest(records)
        report["benchmark"] = {"collected_at": read(replay / "collection.json")["collected_at"] if replay else stamp(),
                               "processed_at": stamp(), "collection_digest": collection_digest,
                               "mode": "frozen-native-replay" if replay else "live-native-no-paid",
                               "gaps": gaps, "source": source_state()}
        if replay:
            report["benchmark"]["timestamp_note"] = (
                "Offline transport replay, not new collection. Generated crawl/request clock values are replay "
                "execution times; original observation times are in the unchanged source requests.json. "
                "Not a client-delivery audit; browser, OS TLS and cookie-state checks are not reverified.")
        write(folder / "report.json", report)
        state = {"status": "complete", "seconds": round(time.monotonic() - begin, 2),
                 "pages": report["page_counts"], "collection_digest": collection_digest}
    except Exception as exc:
        # Avoid dumping arbitrary provider/server response text or secrets into a console.
        state = {"status": "blocked", "error_type": type(exc).__name__, "seconds": round(time.monotonic() - begin, 2)}
    finally:
        transport.close()
        write(folder / "events.json", events)
        if not replay:
            write(folder / "requests.json", records)
            write(folder / "collection.json", {"digest": digest(records), "collected_at": stamp()})
    from maya_audit.models import to_jsonable
    write(folder / "config.json", to_jsonable(cfg))
    write(folder / "result.json", state)
    return state


def score_run(folder, sites):
    rows = []
    for site in sites:
        where = folder / site["id"]
        if not (where / "report.json").exists():
            attempt = read(where / "result.json") if (where / "result.json").exists() else {"status": "not_run"}
            missing = [{"id": label["id"], "expected": group,
                        "result": "unassessed" if label.get("status") == "verified" else "provisional",
                        "finding_ids": []}
                       for group in ("must_find", "must_not_find") for label in site["expectations"][group]]
            rows.append({"site": site["id"], **attempt, "assertions": missing,
                         "counts": dict(Counter(v["result"] for v in missing))})
            continue
        report = read(where / "report.json")
        rows.append({"site": site["id"], **read(where / "result.json"),
                     **score(report, site["expectations"]),
                     "readable_content_pages": ((report.get("audit_status") or {}).get("content_coverage") or {}).get("pages_read"),
                     "phase_timings": (report.get("crawl") or {}).get("steps"),
                     "labels_digest": digest(site["expectations"]),
                     "source_digest": report["benchmark"]["source"]["source_digest"]})
    write(folder / "scorecard.json", {"created_at": stamp(), "sites": rows,
          "warning": "Only independently verified, collection-pinned assertions are scored; no general accuracy percentage."})
    print("site                  hits misses false-alarms negatives provisional unassessed seconds")
    for row in rows:
        c = row.get("counts", {})
        print(f"{row['site']:21} " + " ".join(f"{c.get(k, 0):5}" for k in
              ("hit", "miss", "false_alarm", "correct_negative", "provisional", "unassessed"))
              + f" {row.get('seconds', '-')} {row['status']}")
    return rows


def compare(before, after):
    old = {r["site"]: r for r in before["sites"]}
    results = []
    verified = 0
    for row in after["sites"]:
        prior = old.get(row["site"], {})
        if not row.get("collection_digest") or any(prior.get(k) != row.get(k) for k in ("collection_digest", "labels_digest")):
            raise ValueError("Cannot compare changed evidence or labels: " + row["site"])
        a = {v["id"]: v["result"] for v in prior.get("assertions", [])}
        b = {v["id"]: v["result"] for v in row.get("assertions", [])}
        verified += sum(v in ("hit", "miss", "false_alarm", "correct_negative") for v in a.values())
        regressions = [key for key, value in a.items() if value in ("hit", "correct_negative") and b.get(key) != value]
        results.append({"site": row["site"], "regressions": regressions})
    if set(old) != {r["site"] for r in after["sites"]}:
        raise ValueError("Cannot compare different site sets")
    if not verified:
        raise ValueError("No independently verified scored assertions; cannot establish non-regression")
    return results


def child_environment(folder):
    # An allowlist prevents all inherited provider credentials, including unknown aliases.
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_CTYPE", "USER", "PYTHONPYCACHEPREFIX",
                                    "PLAYWRIGHT_BROWSERS_PATH", "PLAYWRIGHT_NODEJS_PATH") if k in os.environ}
    for key, name in (("HOME", "home"), ("MAYA_AUDIT_HOME", "audit"), ("TMPDIR", "tmp"),
                      ("XDG_CACHE_HOME", "cache"), ("XDG_CONFIG_HOME", "config")):
        path = folder / name
        path.mkdir(parents=True)
        env[key] = str(path)
    env.update(MAYA_AUDIT_ENV_FILE=str(folder / "absent.env"), MAYA_AUDIT_FIRECRAWL="off", PYTHONUNBUFFERED="1")
    return env


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("collect", "replay", "score", "compare", "worker"))
    parser.add_argument("run", nargs="?")
    parser.add_argument("--live", action="store_true", help="Explicitly permit public-site native HTTP/browser requests; never paid providers")
    parser.add_argument("--site", help="Site ID (omit to audit all ten sequentially)")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--after", type=Path)
    args = parser.parse_args(argv)
    # Refused before anything is read: the opt-in does not depend on the corpus, which a release leaves out.
    if args.command == "collect" and not args.live:
        parser.error("Collection makes public requests. Add --live explicitly. Tests must never use it.")
    sites = load_sites()
    if args.site:
        sites = [s for s in sites if s["id"] == args.site]
        if not sites:
            parser.error("Unknown site")
    if args.command == "compare":
        rows = compare(read(Path(args.run) / "scorecard.json"), read(args.after / "scorecard.json"))
        print(json.dumps(rows, indent=2))
        return int(any(row["regressions"] for row in rows))
    if args.command == "score":
        score_run(Path(args.run).resolve(), sites)
        return 0
    if args.command == "worker":
        if not args.site or not args.output or not (args.live or args.run):
            parser.error("Worker requires one site, output and explicit live or replay source")
        state = site_worker(sites[0], args.output, Path(args.run) / args.site if args.run else None)
        print(json.dumps(state))
        return int(state["status"] != "complete")
    if args.command == "collect" and not args.live:
        parser.error("Collection makes public requests. Add --live explicitly. Tests must never use it.")
    if args.command == "replay" and not args.run:
        parser.error("Replay requires the frozen source run directory")
    output = (args.output or ROOT / "output" / "real-sites" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")).resolve()
    output.mkdir(parents=True, exist_ok=False)
    write(output / "run.json", {"started_at": stamp(), "source": source_state(), "command": args.command,
                               "sites": [s["id"] for s in sites], "paid_providers": False,
                               "source_run": str(Path(args.run).resolve()) if args.run else None})
    print("Benchmark output: " + str(output), flush=True)
    for site in sites:
        private = Path(tempfile.mkdtemp(prefix="maya-benchmark-"))
        command = [sys.executable, "-m", "scripts.real_sites_benchmark", "worker", "--site", site["id"],
                   "--output", str(output / site["id"])]
        if args.command == "collect":
            command += ["--live"]
        else:
            command += [str(Path(args.run).resolve())]
        with (output / (site["id"] + ".log")).open("w") as log:
            try:
                subprocess.run(command, cwd=ROOT, env=child_environment(private), stdout=log,
                               stderr=subprocess.STDOUT, timeout=780, check=False)
            except subprocess.TimeoutExpired:
                where = output / site["id"]
                where.mkdir(exist_ok=True)
                write(where / "result.json", {"status": "blocked", "reason": "worker exceeded 780s hard wall", "seconds": 780})
        print(site["id"] + ": completed attempt", flush=True)
        score_run(output, sites)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
