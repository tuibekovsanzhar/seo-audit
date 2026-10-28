"""Audit several brands one after another and write a report per brand plus a summary.

Each brand gets the normal audit: the same settings `crawl` builds, the same URL safety, robots.txt
handling, politeness, per-site lock and DataForSEO cost guard. Brands run one at a time, and a brand
that fails is recorded with its error while the rest carry on.
"""

from __future__ import annotations

import csv
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from .config import CrawlConfig
from .findings import Severity
from .runclock import for_outcome
from .report import (EXIT_COMPLETED, EXIT_DEGRADED, EXIT_ERROR, EXIT_INCOMPLETE, build_report, page_counts, render_markdown,
                     run_outcome)

EXIT_MEANINGS = {EXIT_COMPLETED: "completed", EXIT_DEGRADED: "degraded: the site could not be read properly",
                 EXIT_ERROR: "error: no audit was produced", EXIT_INCOMPLETE: "incomplete: stopped at a page cap or time limit"}
SEVERITIES = [severity.value for severity in Severity]
COLUMNS = ["name", "url", "exit_code", "result", "duration_s", "pages_checked", "redirects", "pages_discovered", "render_mode",
           "pages_rendered", *(f"findings_{severity}" for severity in SEVERITIES), "findings_total",
           "checks_not_assessed", "dfs_status", "dfs_cost_usd", "dfs_from_cache", "error", "json", "markdown"]


class BatchError(ValueError):
    """The batch cannot start: the brands file or the output folder is not usable."""


@dataclass(frozen=True)
class Brand:
    name: str
    url: str
    slug: str  # the file name its reports are written under


def read_brands(path: str) -> list[Brand]:
    """The brands in a CSV file with the columns name and url. Other columns are ignored."""
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            header = [(column or "").strip().lower() for column in reader.fieldnames or []]
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise BatchError(f"cannot read {path}: {exc}") from exc
    if not {"name", "url"} <= set(header):
        raise BatchError(f"{path} needs a header row with the columns name and url (found: {', '.join(header) or 'nothing'})")
    brands, seen = [], {}
    for number, row in enumerate(rows, 2):
        values = {(key or "").strip().lower(): (value or "").strip() for key, value in row.items()
                  if isinstance(key, str) and (isinstance(value, str) or value is None)}
        name, url = values.get("name", ""), values.get("url", "")
        if not name and not url:
            continue
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
        if not slug:
            raise BatchError(f"{path} line {number}: the name {name!r} cannot be used as a file name")
        if slug.lower() in seen:
            raise BatchError(f"{path} line {number}: the name {name!r} would overwrite the reports of line {seen[slug.lower()]}")
        seen[slug.lower()] = number
        brands.append(Brand(name, url, slug))
    if not brands:
        raise BatchError(f"{path} lists no brands")
    return brands


def _url_problem(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return f"not a web address: {url!r} (expected something like https://example.com/)"
    return None


def _outputs(out: Path, brands: list[Brand]) -> list[Path]:
    return [out / f"{brand.slug}{suffix}" for brand in brands for suffix in (".json", ".md", "-evidence")] + [
        out / "summary.csv", out / "summary.md"]


def _dfs_prepare(args, brands: list[Brand]) -> tuple[int | None, Any]:
    """Show the DataForSEO plan for the whole batch and check it against today's budget, before anything is fetched.

    Returns (exit code or None to go on, a function that opens a guarded client for one brand).
    """
    from . import dataforseo as dfs
    from .dataforseo import panel, pricing

    credentials = dfs.load_credentials()
    ledger, cache = panel.open_stores()
    plans = {brand.slug: panel.audit_plan(brand.url) for brand in brands}
    print(f"DataForSEO plan for the batch: {len(brands)} brand(s) (estimates are upper bounds; nothing has been sent)")
    total = 0.0
    for brand in brands:
        lines, cost = panel.preview(plans[brand.slug], ledger, cache, daily_budget=args.dfs_daily_budget, refresh=args.dfs_refresh)
        total += cost
        print(f"  {brand.name}: ${cost:.4f}")
        print("\n".join("  " + line for line in lines[1:len(plans[brand.slug]) + 1]))
    total = round(total, 6)
    try:
        spent = ledger.spent_today()
    except dfs.LedgerCorrupt as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR, None
    remaining = round(max(0.0, args.dfs_daily_budget - spent), 6)
    fits = total <= remaining
    print(f"  Total for the batch: ${total:.4f}")
    print(f"  Spent or reserved today (UTC): ${spent:.4f} of a ${args.dfs_daily_budget:.2f} daily budget; ${remaining:.4f} left")
    print(f"  Fits today's remaining budget: {'yes' if fits else 'NO'}")
    print(f"  Approval needed above: ${pricing.approval_threshold():.2f} for the batch")
    print(f"  Never more than: ${pricing.audit_cap():.2f} for one site")
    if credentials is None:
        print("  Credentials: not set, so every DataForSEO check will be reported as not assessed")
    print()
    if args.dfs_dry_run:
        print("Dry run: no DataForSEO request was sent, no site was crawled and no file was written.")
        return EXIT_COMPLETED, None
    if not fits:
        print(f"error: the batch's DataForSEO plan totals ${total:.4f} and only ${remaining:.4f} of today's "
              f"${args.dfs_daily_budget:.2f} budget is left. Nothing was sent and no site was crawled. Run fewer brands, "
              "wait for the next UTC day, or raise --dfs-daily-budget.", file=sys.stderr)
        return EXIT_ERROR, None
    approved = max(pricing.approval_threshold(), args.dfs_approve_up_to or 0.0)
    if total > approved:
        if not sys.stdin.isatty():
            print(f"error: the batch's DataForSEO plan totals ${total:.4f}, above the ${approved:.2f} approved. "
                  f"Pass --dfs-approve-up-to {total + 0.005:.2f} to allow it. Nothing was sent.", file=sys.stderr)
            return EXIT_ERROR, None
        if input(f"Spend up to ${total:.4f} on DataForSEO for this batch? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("error: DataForSEO spend was not approved; nothing was sent.", file=sys.stderr)
            return EXIT_ERROR, None

    def open_client(brand: Brand):
        # One guarded client per brand: its own audit id in the ledger, the per-audit approval limit, and the
        # per-audit spending limit, which in a batch is therefore a limit for each site.
        # The ledger's daily budget is checked again, under its lock, before every single call.
        client = dfs.DataForSEOClient(credentials, ledger, cache, daily_budget=args.dfs_daily_budget,
                                      approved_usd=pricing.approval_threshold(), audit_cap=pricing.audit_cap(),
                                      approved_always_ask=args.dfs_approve_up_to is not None)
        return client, plans[brand.slug]

    return None, open_client


def _row(brand: Brand) -> dict[str, Any]:
    return {**{column: "" for column in COLUMNS}, "name": brand.name, "url": brand.url}


def _audit_brand(brand: Brand, out: Path, args, config_for: Callable[[str], CrawlConfig],
                 run_audit: Callable[[str, CrawlConfig], Any], open_client) -> dict[str, Any]:
    from .report import write_json, write_markdown

    row = _row(brand)
    problem = _url_problem(brand.url)
    if problem:
        raise BatchError(problem)
    config = config_for(brand.url)
    outcome = run_audit(brand.url, config)
    result, gates, checks = outcome.result, outcome.gates, outcome.checks
    fc_info, fc_pages = None, []
    open_firecrawl = getattr(args, "open_firecrawl", None)
    if open_firecrawl is not None:  # the page reader of every audit, as in `crawl`
        from .firecrawl import panel as fc_panel
        from .firecrawl import reader as fc_reader

        fc_client, fc_options = open_firecrawl(config)
        fc_client.clock = for_outcome(outcome)  # the audit's own deadline and pace
        try:
            fc_raw = fc_reader.apply(outcome, config, fc_client, fc_options)
            fc_pages = fc_raw.get("view_pages") or []
            fc_info = fc_panel.section(fc_raw)
        finally:
            fc_client.close()
    code, word, sentence = run_outcome(result, gates, fc_info)
    site_checks = [check for check in checks if not check.check_id.startswith("ANS")]
    counts = {severity: 0 for severity in SEVERITIES}
    for check in site_checks:
        for finding in check.findings:
            counts[finding.severity.value] += 1
    int3 = next((gate.evidence for gate in gates if gate.check_id == "INT-3"), {})
    row.update(exit_code=code, result=f"{word.lower()}: {sentence}",
               pages_checked=page_counts(result)[0], redirects=page_counts(result)[1],
               pages_discovered=len(result.discovered_urls),
               render_mode=int3.get("rendering_mode") or "not reported",
               pages_rendered=sum(1 for page in int3.get("rendered_pages") or [] if page.get("ok")),
               **{f"findings_{severity}": count for severity, count in counts.items()}, findings_total=sum(counts.values()),
               checks_not_assessed=sum(check.status == "not_assessed" for check in checks))

    from . import brand as brand_module

    # The brand: the CSV's name for this row, as `crawl --dfs-brand` would give it (DECISIONS 212).
    audit_brand = brand_module.resolve(result, brand.name, fc_pages or None)
    report = build_report(result, gates, checks, firecrawl=fc_info, brand=audit_brand)
    markdown = render_markdown(result, gates, checks, firecrawl=fc_info)
    if fc_info is not None:
        report["firecrawl"] = fc_info
        markdown += fc_panel.render_markdown(fc_info)
        row.update(pages_checked=fc_info.get("pages_read") or row["pages_checked"])
    if open_client is not None:
        from .dataforseo import panel

        client, plan = open_client(brand)
        try:
            section = panel.run_checks(plan, client, refresh=args.dfs_refresh)
        finally:
            client.close()
        report["dataforseo"] = section
        markdown += panel.render_markdown(section)
        cached = [call["from_cache"] for call in section["calls"]]
        reasons = "; ".join(check["summary"] for check in section["checks"] if check["status"] == "not_assessed")
        row.update(dfs_status=section["status"] + (f" ({reasons})" if reasons else ""), dfs_cost_usd=f"{section['cost_usd']:.6f}",
                   dfs_from_cache="" if not cached else "yes" if all(cached) else "partly" if any(cached) else "no")
    if getattr(args, "save_evidence", "none") == "all":
        from . import evidence_store

        saved = evidence_store.save_evidence(result, config, out / f"{brand.slug}-evidence", "all")
        report["evidence_saved"] = {"folder": f"{brand.slug}-evidence", "mode": "all", "pages": len(saved["pages"]),
                                    "not_saved": len(saved["not_saved"]), "total_bytes": saved["total_bytes"]}
    json_path, markdown_path = out / f"{brand.slug}.json", out / f"{brand.slug}.md"
    write_json(report, str(json_path), args.overwrite)
    write_markdown(markdown, str(markdown_path), args.overwrite)
    row.update(json=json_path.name, markdown=markdown_path.name)
    return row


def _summary_markdown(rows: list[dict[str, Any]], args, started: str) -> str:
    done = sum(row["exit_code"] in (EXIT_COMPLETED, EXIT_INCOMPLETE) for row in rows)
    lines = [f"# Maya Audit batch: {len(rows)} brand(s)", "", f"**Started:** {started}  ",
             f"**Brands file:** {args.brands}  ", f"**Page cap per brand:** {args.max_pages}  ",
             f"**Reports produced:** {done} of {len(rows)}", ""]
    if args.dataforseo:
        spend = sum(float(row["dfs_cost_usd"] or 0) for row in rows)
        lines += [f"**DataForSEO spend for the batch:** ${spend:.4f}", ""]
    lines += ["| Brand | URL | Exit | Duration (s) | Pages checked (of URLs discovered) | Rendering | Findings " + " / ".join(SEVERITIES)
              + " | Not assessed | DataForSEO | Reports |", "|---|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        ok = row["json"] != ""
        dfs = "" if not row["dfs_status"] else (f"{row['dfs_status'].split(' (')[0]}, ${float(row['dfs_cost_usd']):.4f}"
                                                 + {"yes": " (from cache)", "partly": " (partly from cache)"}.get(row["dfs_from_cache"], ""))
        lines.append(
            f"| {row['name']} | {row['url']} | {row['exit_code']} {EXIT_MEANINGS[row['exit_code']].split(':')[0]} | {row['duration_s']} | "
            + (f"{row['pages_checked']} page{'' if row['pages_checked'] == 1 else 's'}"
               + (f" + {row['redirects']} redirect{'' if row['redirects'] == 1 else 's'}" if row['redirects'] else "")
               + f" (of {row['pages_discovered']}) | {row['render_mode']}, {row['pages_rendered']} rendered | "
               f"{' / '.join(str(row[f'findings_{severity}']) for severity in SEVERITIES)} | {row['checks_not_assessed']} | {dfs} | "
               f"[md]({row['markdown']}), [json]({row['json']}) |" if ok else "- | - | - | - | - | none |"))
    lines += ["", "Exit codes: " + "; ".join(f"{code} = {meaning}" for code, meaning in sorted(EXIT_MEANINGS.items())) + ".",
              "", "\"Not assessed\" counts every check that could not run, including the five answer-engine checks "
              "(ANS) when no citation file was supplied. Findings exclude that panel."]
    problems = [row for row in rows if row["error"] or row["exit_code"] in (EXIT_DEGRADED, EXIT_INCOMPLETE)]
    if problems:
        lines += ["", "## Brands that need a look", ""]
        lines += [f"- **{row['name']}** (exit {row['exit_code']}): {row['error'] or row['result']}" for row in problems]
    return "\n".join(lines) + "\n"


def run(args, config_for: Callable[[str], CrawlConfig], run_audit: Callable[[str, CrawlConfig], Any]) -> int:
    """Run the batch. 0: every brand has a usable report. 1: at least one failed or was degraded. 2: it could not start."""
    from datetime import datetime, timezone

    try:
        brands = read_brands(args.brands)
    except BatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    out = Path(args.out).expanduser()
    if not args.dfs_dry_run:
        if out.exists() and not out.is_dir():
            print(f"error: --out is not a folder: {out}", file=sys.stderr)
            return EXIT_ERROR
        existing = [path.name for path in _outputs(out, brands) if path.exists()]
        if existing and not args.overwrite:
            print(f"error: {out} already holds {', '.join(existing[:6])}{' ...' if len(existing) > 6 else ''}; "
                  "choose a new folder or pass --overwrite", file=sys.stderr)
            return EXIT_ERROR

    open_client = None
    if args.dataforseo or args.dfs_dry_run:
        code, open_client = _dfs_prepare(args, brands)
        if code is not None:
            return code
    out.mkdir(parents=True, exist_ok=True)

    started, rows = datetime.now(timezone.utc).isoformat(timespec="seconds"), []
    for number, brand in enumerate(brands, 1):
        print(f"[{number}/{len(brands)}] {brand.name}  {brand.url}", flush=True)
        clock = time.monotonic()
        try:
            row = _audit_brand(brand, out, args, config_for, run_audit, open_client)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # one brand failing must not stop the others
            row = _row(brand)
            row.update(exit_code=EXIT_ERROR, result=EXIT_MEANINGS[EXIT_ERROR], error=f"{type(exc).__name__}: {str(exc)[:500]}")
        row["duration_s"] = f"{time.monotonic() - clock:.1f}"
        rows.append(row)
        print(f"      exit {row['exit_code']} ({EXIT_MEANINGS[row['exit_code']].split(':')[0]}) in {row['duration_s']}s"
              + (f"; DataForSEO ${float(row['dfs_cost_usd']):.4f}" if row["dfs_cost_usd"] else "")
              + (f"; {row['error']}" if row["error"] else ""), flush=True)

    with open(out / "summary.csv", "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    (out / "summary.md").write_text(_summary_markdown(rows, args, started), encoding="utf-8", newline="\n")
    usable = sum(row["exit_code"] in (EXIT_COMPLETED, EXIT_INCOMPLETE) for row in rows)
    print(f"\n{usable} of {len(rows)} brand(s) have a usable report. Summary: {out / 'summary.md'} and {out / 'summary.csv'}")
    return EXIT_COMPLETED if usable == len(rows) else EXIT_DEGRADED
