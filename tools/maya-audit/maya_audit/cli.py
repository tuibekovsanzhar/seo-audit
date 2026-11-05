from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .audit import NetworkPreflightFailed, run_audit
from .botinfo import BotInfoPageNotReady
from .config import (FAST_EXTERNAL_LINK_CHECKS_MAX, FAST_IMAGE_CHECKS_MAX, FAST_KEY_IMAGE_CHECKS_MAX,
                     FAST_LLMS_LINK_CHECKS_MAX, FAST_RENDER_BUDGET,
                     FAST_SITEMAP_CHECK_MAX, QUICK_SITEMAP_CHECK_MAX, STANDARD_SITEMAP_CHECK_MAX, CrawlConfig, default_time_limit_s, estimated_duration_s, external_link_cap)
from .runclock import for_outcome, reader_allowance_s
from .crawler import ConcurrentCrawlError, HostNotAllowed
from .intent import DeclaredPolicy, IntentMarking
from .ai_skills import skill_names
from .report import (build_llm_brief, render_markdown, render_markdown_brief, render_text, run_outcome, write_json,
                     write_llm_brief, write_markdown)


def _ip_range(value: str) -> tuple[str, str]:
    token, sep, path = value.partition("=")
    if not sep or not token or not path:
        raise argparse.ArgumentTypeError("expected TOKEN=PATH, e.g. OAI-SearchBot=searchbot.json")
    return token, path


def _critical_fact(value: str) -> tuple[str, str]:
    page, sep, fact = value.partition("=")
    if not sep or not page.strip() or not fact.strip():
        raise argparse.ArgumentTypeError("expected PAGE=TEXT, e.g. /pricing=Pro plan $49/mo")
    return page.strip(), fact.strip()


def _markings(path: str | None) -> tuple[IntentMarking, ...]:
    if not path:
        return ()
    with open(path, encoding="utf-8") as fh:
        return tuple(IntentMarking(**item) for item in json.load(fh))


def _output_preflight(args) -> str | None:
    """Reject output collisions before the crawl makes any network requests."""
    outputs = [path for path in (args.json_path, args.markdown_path, getattr(args, "markdown_brief_path", None), args.llm_brief_path) if path]
    seen: set[str] = set()
    for raw_path in outputs:
        path = Path(raw_path).expanduser()
        identity = str(path.resolve())
        if identity in seen:
            return f"output paths must be different: {raw_path}"
        seen.add(identity)
        if path.is_dir():
            return f"output path is a directory: {raw_path}"
        if not args.overwrite and os.path.lexists(path):
            return f"output already exists: {raw_path}; choose a new path or pass --overwrite"
    return None


def _migrate(source: str, target: str) -> int:
    from .migrate import migrate_report

    with open(source, encoding="utf-8") as fh:
        report = json.load(fh)
    try:
        migrated = migrate_report(report)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    write_json(migrated, target)
    for change in (migrated.get("migrated") or {}).get("status_changes", []):
        print(f"{change['check_id']:7} {change['from']} -> {change['to']}")
    print(f"migrated report written to {target}")
    return 0


def _dfs_command(args) -> int:
    from . import dataforseo as dfs
    from .dataforseo import panel

    credentials = dfs.load_credentials()
    if credentials is None:
        print("error: DataForSEO credentials are not set. Put MAYA_AUDIT_DATAFORSEO_LOGIN and "
              "MAYA_AUDIT_DATAFORSEO_PASSWORD in the environment or in a git-ignored .env file.", file=sys.stderr)
        return 2
    ledger, _cache = panel.open_stores()
    try:
        print("\n".join(panel.balance_report(credentials, ledger, all_prices=args.all_prices)))
    except RuntimeError as exc:
        print(f"error: {credentials.redact(str(exc))}", file=sys.stderr)
        return 2
    return 0


def _dfs_prepare(args):
    """Show the DataForSEO plan before anything is fetched. Returns (exit code or None, client, plan)."""
    from . import dataforseo as dfs
    from .dataforseo import panel, pricing

    credentials = dfs.load_credentials()
    ledger, cache = panel.open_stores()
    plan = panel.audit_plan(args.url) if args.dataforseo or not args.dfs_search_data else []
    if args.dfs_search_data:
        from .dataforseo import insights

        # A country that was typed and is not recognised is an error, not a silent United States (DECISIONS 179).
        typed = (args.dfs_country or "").strip()
        if typed and not insights.location_for(typed)[3] and not args.dfs_default_market:
            print(f"error: --dfs-country {typed!r} is not a country this tool can ask DataForSEO about, so the search data "
                  f"would be for the United States. Spellings it knows include: {insights.known_spellings()}. "
                  "Correct it, or pass --dfs-default-market to use United States figures. Nothing was sent.", file=sys.stderr)
            return 2, None, []
        plan += insights.audit_plan(args.url, country=args.dfs_country, brand=args.dfs_brand, key_pages=args.key_page or [],
                                    local_business=args.dfs_local_business)
    lines, total = panel.preview(plan, ledger, cache, daily_budget=args.dfs_daily_budget, refresh=args.dfs_refresh)
    if credentials is None:
        lines.append("  Credentials: not set, so every DataForSEO check will be reported as not assessed")
    print("\n".join(lines) + "\n")
    if args.dfs_dry_run:
        print("Dry run: no DataForSEO request was sent and the site was not crawled.")
        return 0, None, plan
    approved = max(pricing.approval_threshold(), args.dfs_approve_up_to or 0.0)
    if total > approved:
        if not sys.stdin.isatty():
            print(f"error: this audit's DataForSEO plan totals ${total:.4f}, above the ${approved:.2f} approved. "
                  f"Pass --dfs-approve-up-to {total:.2f} to allow it.", file=sys.stderr)
            return 2, None, plan
        if input(f"Spend up to ${total:.4f} on DataForSEO for this audit? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("error: DataForSEO spend was not approved; nothing was sent.", file=sys.stderr)
            return 2, None, plan
        approved = total
    client = dfs.DataForSEOClient(credentials, ledger, cache, daily_budget=args.dfs_daily_budget,
                                  approved_usd=approved, approved_always_ask=args.dfs_approve_up_to is not None)
    return None, client, plan


def _firecrawl_prepare(args, automatic: bool = False):
    """Show the Firecrawl plan before anything is fetched. Returns (exit code or None, client, options).

    Firecrawl is the page reader of every audit, so the basic proxy needs no confirmation: its credits are recorded in
    the ledger and held under the daily guard. A stronger proxy (the site owner's approval) is still confirmed.
    `automatic` is a run that did not name Firecrawl at all: if it cannot be used, the audit goes on without it.
    """
    from . import firecrawl as fc
    from .firecrawl import panel, settings

    cap = args.firecrawl_max_pages if args.firecrawl_max_pages is not None else max(1, min(args.max_pages, settings.MAX_PAGES_LIMIT))
    options = fc.Options(read_blocked=True, read_always=True, sitemap_discovery=True, render_fallback=args.firecrawl_render, max_pages=cap,
                         proxy=args.firecrawl_proxy, owner_approved_bypass=args.firecrawl_owner_approved,
                         allow_without_zero_data_retention=args.firecrawl_allow_without_zdr or not settings.zero_data_retention_wanted(),
                         concurrency=(args.firecrawl_concurrency if getattr(args, "firecrawl_concurrency", None) is not None
                                      else settings.concurrency()),
                         gap_s=getattr(args, "firecrawl_gap", None))
    key = fc.load_key()
    ledger, cache = fc.open_stores()
    shown = panel.plan(options, args.max_pages, ledger, key is not None, args.firecrawl_daily_credits)
    print("\n".join(panel.plan_lines(shown)) + "\n")
    if args.firecrawl_dry_run:
        print("Dry run: no Firecrawl request was sent and the site was not crawled.")
        return 0, None, options
    if shown["blocked"]:
        if automatic:
            print(f"note: Firecrawl is not used for this audit: {shown['blocked']['message']}", file=sys.stderr)
            return None, None, options
        print(f"error: {shown['blocked']['message']}", file=sys.stderr)
        return 2, None, options
    top = shown["max_credits"]
    if args.firecrawl_approve_up_to is not None:
        if args.firecrawl_approve_up_to < top:
            print(f"error: this audit's Firecrawl plan could use {top} credits, above the {args.firecrawl_approve_up_to:g} confirmed. "
                  f"Pass --firecrawl-approve-up-to {top} to allow it, or lower --firecrawl-max-pages.", file=sys.stderr)
            return 2, None, options
    elif options.proxy == settings.DEFAULT_PROXY:
        pass  # the page reader of a normal run: recorded and guarded, not asked about
    elif not sys.stdin.isatty():
        print(f"error: Firecrawl needs a confirmation of its cost. Pass --firecrawl-approve-up-to {top}.", file=sys.stderr)
        return 2, None, options
    else:
        warning = (" Page content MAY BE STORED by Firecrawl (zero data retention is off)." if options.allow_without_zero_data_retention else "")
        if input(f"Confirm up to {top} Firecrawl credits for this audit?{warning} [y/N] ").strip().lower() not in {"y", "yes"}:
            print("error: Firecrawl spend was not confirmed; nothing was sent.", file=sys.stderr)
            return 2, None, options
    client = fc.FirecrawlClient(key, ledger, cache, approved_credits=top, max_pages=options.max_pages,
                                daily_credits=shown["daily_credits"], proxy=options.proxy,
                                owner_approved_bypass=options.owner_approved_bypass,
                                allow_without_zero_data_retention=options.allow_without_zero_data_retention,
                                resumed=bool(getattr(args, "resume", False)))  # A16: a resume re-reads its own copies
    return None, client, options


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="maya-audit", description="Maya technical audit (INT gates, ACC, IDX, RND, STR, PRF checks and the ANS panel)")
    sub = parser.add_subparsers(dest="command", required=True)

    crawl = sub.add_parser("crawl", help="crawl a site and report INT-1..INT-4, ACC-1..ACC-8, IDX-1..IDX-10, RND-1..RND-7, STR-1..STR-13, TSEO-1, PRF-1..PRF-3, ANS-1..ANS-5")
    crawl.add_argument("url")
    crawl.add_argument("--max-pages", type=int, default=50)
    crawl.add_argument("--business-type", default="auto", metavar="ID",
                       help="business type for page importance and key pages (DECISIONS 311): auto (suggested) or one of "
                            "eticaret, bankacilik, yatirim, kart, saglik, otomotiv, saas, su_aritma, guvenlik, "
                            "ev_hizmetleri, gida, seyahat, restoran, diger")
    crawl.add_argument("--single-page", action="store_true",
                       help="audit only the address given: one page, no links followed, no sitemap. Site-level facts the page "
                            "depends on (robots.txt, its redirects, http:// to https://) are still checked")
    crawl.add_argument("--time-limit", type=float, default=None,
                       help="seconds for the whole audit (default: scaled to the page cap and key pages, at least 300)")
    crawl.add_argument("--block-loopback", action="store_true",
                       help="hosted-use safety: refuse localhost/private loopback targets (off for local development)")
    crawl.add_argument("--timeout", type=float, default=15.0, help="per-request timeout, seconds")
    crawl.add_argument("--delay", type=float, default=1.0, help="minimum seconds between requests")
    crawl.add_argument("--max-crawl-delay", type=float, default=90.0, help="ceiling for a declared Crawl-delay, seconds")
    crawl.add_argument("--key-page", action="append", default=[], help="user-marked key page (repeatable)")
    crawl.add_argument("--allow-live-host", action="append", default=[],
                       help="allow an additional host for a redirect or optional cross-origin check; the start host is automatic")
    crawl.add_argument("--bot-info-url", default=os.environ.get("MAYA_AUDIT_BOT_INFO_URL"),
                       help="optional public page explaining Maya-Audit; a missing page is reported but does not stop the crawl "
                            "(default: $MAYA_AUDIT_BOT_INFO_URL)")
    crawl.add_argument("--training-bots", choices=["allow", "block"], help="declared policy for AI training bots")
    crawl.add_argument("--search-bots", choices=["allow", "block"], default="allow",
                       help="declared policy for AI search bots (default: allow)")
    crawl.add_argument("--intent-markings", help="JSON file with a list of intent markings (spec §2.5)")
    crawl.add_argument("--site-verification-token",
                       help='token expected in <meta name="maya-site-verification"> on the homepage; enables ACC-4 probes')
    crawl.add_argument("--verify-dns", action="store_true",
                       help="also accept the token as a DNS TXT record on the domain (maya-site-verification=TOKEN); one lookup "
                            "through a public DNS-over-HTTPS resolver")
    crawl.add_argument("--no-probes", action="store_true", help="never send ACC-4 probes, even on verified sites")
    crawl.add_argument("--no-verification", action="store_true",
                       help="do not ask the most serious findings again before writing the report (DECISIONS 272)")
    crawl.add_argument("--robots-sample-interval", type=float, default=120.0,
                       help="seconds between the ACC-1 robots.txt re-fetches")
    crawl.add_argument("--access-log", action="append", default=[], help="access log file for ACC-5 (repeatable)")
    crawl.add_argument("--access-log-format", choices=["combined", "cloudflare_logpush"], default="combined",
                       help="combined = nginx combined format; cloudflare_logpush = Cloudflare http_requests NDJSON")
    crawl.add_argument("--ip-ranges", action="append", type=_ip_range, default=[],
                       help="TOKEN=PATH to a local copy of a bot's published IP ranges (repeatable)")
    crawl.add_argument("--gsc-site-url", help="Search Console property URL for IDX-9 (token from $MAYA_AUDIT_GSC_TOKEN)")
    crawl.add_argument("--bing-site-url", help="Bing Webmaster Tools site URL for IDX-10 (key from $MAYA_AUDIT_BING_API_KEY)")
    crawl.add_argument("--indexnow-key", help="IndexNow key to verify (IDX-10)")
    crawl.add_argument("--indexnow-key-location", help="IndexNow key file URL, if not /{key}.txt")
    crawl.add_argument("--no-render", action="store_true", help="skip T1 rendering; RND uses raw-HTML heuristics only")
    crawl.add_argument("--render-budget", type=int, default=20, help="pages rendered in a headless browser (default 20)")
    crawl.add_argument("--render-third-party", action="store_true",
                       help="let the headless browser load resources from other origins (off by default)")
    crawl.add_argument("--render-browser-channel", metavar="CHANNEL",
                       help="render with an installed browser instead of Playwright's Chromium, "
                            "e.g. chrome, chrome-beta, msedge (default: Playwright's Chromium)")
    crawl.add_argument("--critical-fact", action="append", type=_critical_fact, default=[], metavar="PAGE=TEXT",
                       help="declared critical fact for RND-2, e.g. /pricing='Pro plan $49/mo' (repeatable)")
    crawl.add_argument("--brand-family-domain", action="append", default=[], type=_brand_family_domain, metavar="DOMAIN",
                       help="another domain of the same brand, as a plain host name such as other-shop.example (repeatable). "
                            "A link to it is not reported as a link to another site and is never requested")
    crawl.add_argument("--no-external-links", action="store_true",
                       help="do not ask links to other sites whether they still exist (on by default: one HEAD request each, "
                            "each site's robots.txt obeyed first, at most 20 + pages read and 100 requests, 25 sites; "
                            "sameAs profile links are still asked, at most 10)")
    crawl.add_argument("--fast", action="store_true",
                       help="Fast check: render 6 pages instead of 20 and check at most 50 sitemap addresses, 20 llms.txt "
                            "links, 10 images and 30 requests to other sites (instead of 200, 50, 30 and 100). The pages "
                            "read, robots.txt samples, ACC-4, redirect re-checks, the page reader and paid data are unchanged")
    crawl.add_argument("--check-external-links", action="store_true",
                       help="still accepted: links to other sites are checked by default now (see --no-external-links)")
    crawl.add_argument("--sitemap-check-max", type=_sitemap_check_max, default=None, metavar="N",
                       help="IDX-5: ask at most N sitemap URLs the crawl did not read, one light request each (0 to 1000; "
                            "default 200, 1000 from --max-pages 500, 0 with --single-page)")
    crawl.add_argument("--no-soft-404-probe", action="store_true",
                       help="do not send IDX-1's one request for a made-up address (which checks that missing pages answer 404)")
    crawl.add_argument("--no-prf", action="store_true",
                       help="skip PRF-1/PRF-2's extra fetch rounds (their results become Not assessed)")
    crawl.add_argument("--prf-round-gap", type=float, default=30.0, help="seconds between PRF fetch rounds (default 30)")
    crawl.add_argument("--egress-region", help="where Maya's requests leave from, shown with PRF-1 timings")
    crawl.add_argument("--pagespeed", action="store_true",
                       help="PRF-3: PageSpeed Insights lab runs (ownership-verified sites only) and CrUX field data; "
                            "API key from $MAYA_AUDIT_GOOGLE_API_KEY")
    crawl.add_argument("--citations", help="JSON file of answer-engine citation records (T4, produced upstream) for "
                                          "the ANS panel; see maya_audit/ans_data.py for the shape")
    crawl.add_argument("--citation-domains", dest="citation_domains",
                       help="JSON file ranking every domain the engines cited on this brand's prompts "
                            "(T4, Maya get_citations output) for ANS-4/ANS-5; see maya_audit/ans_domains.py")
    crawl.add_argument("--db-path", dest="db_path",
                       help="keep the crawl frontier in this SQLite file instead of memory, so the crawl "
                            "can be resumed; without it a crawl cannot be continued")
    crawl.add_argument("--resume", action="store_true",
                       help="continue the crawl in --db-path instead of starting a new one. Each session "
                            "re-fetches robots.txt and inherits the previous session's backoff delay; the "
                            "INT gates report per session and say the audit was assembled from several")
    crawl.add_argument("--dataforseo", action="store_true",
                       help="add the DataForSEO panel (third-party data). Credentials come from "
                            "MAYA_AUDIT_DATAFORSEO_LOGIN / MAYA_AUDIT_DATAFORSEO_PASSWORD, never from the command line")
    crawl.add_argument("--dfs-search-data", action="store_true",
                       help="add the DataForSEO search data panels (paid): domain overview, ranked keywords, quick wins, organic "
                            "competitors, AI mentions, and a Lighthouse test of the homepage and up to two key pages")
    crawl.add_argument("--dfs-country", metavar="COUNTRY",
                       help="the market for the search data panels, e.g. Turkey, Türkiye or TR (left out: United States). "
                            "A country that is not recognised is an error unless --dfs-default-market is given")
    crawl.add_argument("--dfs-default-market", action="store_true",
                       help="with --dfs-search-data: use United States figures when --dfs-country is not recognised")
    crawl.add_argument("--dfs-brand", metavar="NAME", help="the brand name, for the Google Business Profile lookup")
    crawl.add_argument("--dfs-local-business", action="store_true",
                       help="with --dfs-search-data and --dfs-brand: also look up the Google Business Profile")
    crawl.add_argument("--archives", action="store_true",
                       help="if neither Maya's crawler nor Firecrawl could read the site, read archived copies (Wayback Machine, "
                            "Common Crawl; free). They are reported apart, with their dates; the live site may differ")
    crawl.add_argument("--dfs-dry-run", action="store_true",
                       help="print the DataForSEO plan and its estimated total, send nothing, and exit")
    crawl.add_argument("--dfs-approve-up-to", type=float, metavar="USD",
                       help="approve DataForSEO spend up to this amount for this audit (needed above $2.00, or "
                            "MAYA_AUDIT_DATAFORSEO_CONFIRM_ABOVE_USD; one audit never spends more than $5.00, or "
                            "MAYA_AUDIT_DATAFORSEO_AUDIT_CAP_USD, whatever is approved)")
    crawl.add_argument("--dfs-daily-budget", type=float, default=None, metavar="USD",
                       help="stop paid DataForSEO calls once today's spend would pass this (default 20.00, or MAYA_AUDIT_DATAFORSEO_DAILY_USD)")
    crawl.add_argument("--dfs-refresh", action="store_true", help="ignore cached DataForSEO responses and ask again")
    crawl.add_argument("--firecrawl", action="store_true",
                       help="read page content through Firecrawl (a paid third-party reader). This is the default whenever "
                            "MAYA_AUDIT_FIRECRAWL_API_KEY is set; the flag makes a missing key an error. Maya's own crawler "
                            "still makes the direct requests: robots.txt, sitemap, redirects, headers, timing, the bot-access test")
    crawl.add_argument("--reader-seconds-per-page", type=float, default=None, metavar="SECONDS",
                       help="time assumed for one page through the page reader, beside the delay, when the audit's time is "
                            "divided between Maya's own crawl and the reader (default 8, or MAYA_AUDIT_READER_SECONDS_PER_PAGE)")
    crawl.add_argument("--no-firecrawl", action="store_true",
                       help="do not use Firecrawl for this audit: Maya's own crawler reads the pages")
    crawl.add_argument("--firecrawl-render", action="store_true",
                       help="also allow Firecrawl to render the sampled pages, only if the local browser cannot start")
    crawl.add_argument("--firecrawl-max-pages", type=int, default=None, metavar="N",
                       help="most pages Firecrawl may read in this audit (default: the audit's own page cap, at most 500)")
    crawl.add_argument("--firecrawl-concurrency", type=_one_to_ten, default=None, metavar="N",
                       help="Firecrawl requests in flight at once, 1 to 10 (default: MAYA_AUDIT_FIRECRAWL_CONCURRENCY, else 5). "
                            "Backs off to 2, then 1, on a 429, a 5xx or a timeout reported for the site")
    crawl.add_argument("--firecrawl-gap", type=_gap_seconds, default=None, metavar="S",
                       help="seconds between Firecrawl request starts, 0.2 to 30 (default: MAYA_AUDIT_FIRECRAWL_GAP_S, else 1). "
                            "Firecrawl's own pace; Maya's crawler keeps its polite gap. Doubles at each back-off step")
    crawl.add_argument("--site-concurrency", type=_one_to_ten, default=None, metavar="N",
                       help="Maya's own requests to the audited site in flight at once after the crawl, 1 to 10 (default 5); "
                            "starts stay the polite gap apart. The page reader keeps its own pace")
    crawl.add_argument("--firecrawl-dry-run", action="store_true",
                       help="print the Firecrawl plan and its maximum credits, send nothing, crawl nothing, and exit")
    crawl.add_argument("--firecrawl-approve-up-to", type=float, metavar="CREDITS",
                       help="confirm Firecrawl spend up to this many credits for this audit. Needed only with a stronger proxy "
                            "(asked on the terminal otherwise); the basic proxy runs without a confirmation")
    crawl.add_argument("--firecrawl-daily-credits", type=float, default=None, metavar="CREDITS",
                       help="stop Firecrawl requests once today's credits would pass this (default 10000, or "
                            "MAYA_AUDIT_FIRECRAWL_DAILY_CREDITS)")
    crawl.add_argument("--firecrawl-proxy", choices=["basic", "enhanced", "auto"], default="basic",
                       help="Firecrawl proxy (default basic). enhanced and auto exist to get past bot protection and need "
                            "--firecrawl-owner-approved")
    crawl.add_argument("--firecrawl-owner-approved", action="store_true",
                       help="state that the site owner has approved bypassing bot protection for this audit (recorded in the report)")
    crawl.add_argument("--firecrawl-allow-without-zdr", action="store_true",
                       help="proceed without zero data retention: page content may be stored by Firecrawl. Use only after "
                            "Firecrawl refused zero data retention and you accept that for this audit")
    crawl.add_argument("--save-evidence", choices=["key", "all", "none"], default="key",
                       help="save what each page said (title, meta tags, headings, JSON-LD, main text) so findings can be "
                            "checked later without crawling again: for key pages (default), all pages, or none")
    crawl.add_argument("--evidence-dir", help="folder for --save-evidence (default: <json name>-evidence next to --json, "
                                              "else output/evidence/<host>/)")
    crawl.add_argument("--json", dest="json_path", help="write the full evidence report to this path")
    crawl.add_argument("--markdown", dest="markdown_path", help="write a readable Markdown report to this path")
    crawl.add_argument("--markdown-brief", dest="markdown_brief_path",
                       help="write a short Markdown report (summary, first 10 fixes, impact and effort, checks that "
                            "could not run; about two pages) to this path; --markdown stays the full report")
    crawl.add_argument("--overwrite", action="store_true", help="replace existing output files (default: refuse)")
    crawl.add_argument("--llm-brief", dest="llm_brief_path",
                       help="write the report paired with the reasoning-framework prompts to this path, ready "
                            f"to hand to a model; skills: {', '.join(skill_names())}")
    crawl.add_argument("--llm-skill", dest="llm_skills", action="append", metavar="NAME",
                       help="limit --llm-brief to this skill (repeatable); default is all of them")

    migrate = sub.add_parser("migrate-report",
                             help="upgrade a saved 0.3 JSON report to 0.4 statuses (partial/observed) from its "
                                  "recorded evidence; nothing is fetched or re-run")
    migrate.add_argument("report", help="the saved report (JSON)")
    migrate.add_argument("output", help="where to write the migrated report")

    brief_check = sub.add_parser("brief-check", help="flag claims in a model's document that cite no known check, "
                                                     "numbers not in the audit, and scores (E-R3)")
    brief_check.add_argument("argv", nargs=argparse.REMAINDER, help="brief.json document.md [--report R] [--json]")

    dfs_parser = sub.add_parser("dfs", help="DataForSEO account tools")
    dfs_sub = dfs_parser.add_subparsers(dest="dfs_command", required=True)
    balance = dfs_sub.add_parser("balance", help="show the account balance, today's spend and the account's prices for "
                                                 "the endpoints Maya uses (calls only the free /v3/appendix/user_data endpoint)")
    balance.add_argument("--all-prices", action="store_true",
                         help="also print every price the account lists (several thousand lines)")

    batch = sub.add_parser("batch", help="audit several brands one after another from a CSV file (columns: name, url) "
                                         "and write a report per brand plus a summary")
    batch.add_argument("brands", help="CSV file with a header row and the columns name and url")
    batch.add_argument("--out", required=True, help="folder for <name>.json, <name>.md, summary.csv and summary.md")
    batch.add_argument("--max-pages", type=int, default=50, help="page cap for each brand (default 50)")
    batch.add_argument("--time-limit", type=float, default=None,
                       help="seconds for each brand (default: scaled to the page cap, at least 300)")
    batch.add_argument("--delay", type=float, default=1.0, help="minimum seconds between requests to a site")
    batch.add_argument("--no-render", action="store_true", help="skip rendering for every brand")
    batch.add_argument("--render-browser-channel", metavar="CHANNEL", help="as for crawl")
    batch.add_argument("--no-firecrawl", action="store_true",
                       help="do not read pages through Firecrawl (the default whenever MAYA_AUDIT_FIRECRAWL_API_KEY is set, as for crawl)")
    batch.add_argument("--dataforseo", action="store_true", help="add the DataForSEO panel to every brand's audit")
    batch.add_argument("--dfs-dry-run", action="store_true",
                       help="print the DataForSEO plan and total for the whole batch, send nothing, crawl nothing")
    batch.add_argument("--dfs-approve-up-to", type=float, metavar="USD",
                       help="approve DataForSEO spend up to this amount for the whole batch (needed above $2.00, or "
                            "MAYA_AUDIT_DATAFORSEO_CONFIRM_ABOVE_USD; each site never spends more than $5.00, or "
                            "MAYA_AUDIT_DATAFORSEO_AUDIT_CAP_USD)")
    batch.add_argument("--dfs-daily-budget", type=float, default=None, metavar="USD",
                       help="the batch does not start unless its planned DataForSEO total fits what is left of this today")
    batch.add_argument("--dfs-refresh", action="store_true", help="ignore cached DataForSEO responses and ask again")
    batch.add_argument("--save-evidence", choices=["all", "none"], default="none",
                       help="'all' saves what every checked page said into <out>/<name>-evidence/ (default: none; a batch "
                            "has no key pages)")
    batch.add_argument("--overwrite", action="store_true", help="replace existing output files (default: refuse)")
    return parser


def _reader_reserve(args) -> float:
    """Seconds of the audit's time kept for a page reader, when one will read the pages. With a time limit given on the
    command line the reserve comes out of it (at most half); without one it is added to the default limit."""
    if not getattr(args, "reader_planned", False):
        return 0.0
    from .firecrawl import settings as fc_settings

    at_once = getattr(args, "firecrawl_concurrency", None) or fc_settings.concurrency()
    wanted = reader_allowance_s(min(args.max_pages, 500), args.delay, getattr(args, "reader_seconds_per_page", None), at_once)
    return wanted if args.time_limit is None else min(wanted, max(0.0, args.time_limit) / 2)


def _time_limit(args) -> float:
    """The time limit asked for, or one that fits the run. Warns when the one asked for looks too short."""
    shape = dict(max_pages=args.max_pages, key_pages=len(args.key_page), delay_s=args.delay,
                 render=not args.no_render, render_budget=render_budget(args), prf=not args.no_prf,
                 sitemap_check=sitemap_check_cap(args), external_links=external_requests_cap(args))
    if args.time_limit is None:
        # One time limit for the whole audit: when a page reader will read the pages too, it gets time for that.
        return default_time_limit_s(**shape) + _reader_reserve(args)
    estimate = estimated_duration_s(**shape)
    if args.time_limit < estimate and args.time_limit > 0:
        print(f"warning: --time-limit {args.time_limit:g} is below the estimated {estimate:.0f} s for {args.max_pages} pages"
              f"{f' and {len(args.key_page)} key pages' if args.key_page else ''}. The audit will stop early and report "
              f"which checks were cut. Leave --time-limit out to use {default_time_limit_s(**shape):g} s.", file=sys.stderr)
    return args.time_limit


def _gap_seconds(text: str) -> float:
    """Seconds between Firecrawl request starts, 0.2 to 30 (DECISIONS 295)."""
    from .firecrawl import settings as fc_settings

    try:
        value = float(text)
    except ValueError:
        value = -1.0
    if not fc_settings.MIN_GAP_S <= value <= fc_settings.MAX_GAP_S:
        raise argparse.ArgumentTypeError(f"not a number of seconds from {fc_settings.MIN_GAP_S:g} to {fc_settings.MAX_GAP_S:g}: {text[:20]!r}")
    return value


def _one_to_ten(text: str) -> int:
    """A whole number from 1 to 10 (requests in flight at once, DECISIONS 294)."""
    try:
        value = int(text)
    except ValueError:
        value = 0
    if not 1 <= value <= 10:
        raise argparse.ArgumentTypeError(f"not a number from 1 to 10: {text[:20]!r}")
    return value


def _sitemap_check_max(text: str) -> int:
    """One --sitemap-check-max value: a whole number from 0 to 1000."""
    try:
        value = int(text)
    except ValueError:
        value = -1
    if not 0 <= value <= 1000:
        raise argparse.ArgumentTypeError(f"not a number from 0 to 1000: {text[:20]!r}")
    return value


def fast(args) -> bool:
    return bool(getattr(args, "fast", False))


def render_budget(args) -> int:
    """Pages rendered: --render-budget, at most 6 with --fast (DECISIONS 219)."""
    budget = getattr(args, "render_budget", CrawlConfig.render_budget)
    return min(budget, FAST_RENDER_BUDGET) if fast(args) else budget


def sitemap_check_cap(args) -> int:
    """How many sitemap URLs IDX-5 may ask with a light request (DECISIONS 206, 294): the value given, else 0 for a
    single page, 300 from 500 pages (the web app's Standard), 100 below (Quick, and the command line's default). At most
    50 with --fast (DECISIONS 219)."""
    given = getattr(args, "sitemap_check_max", None)
    if getattr(args, "single_page", False):
        return 0
    cap = given if given is not None else STANDARD_SITEMAP_CHECK_MAX if args.max_pages >= 500 else QUICK_SITEMAP_CHECK_MAX
    return min(cap, FAST_SITEMAP_CHECK_MAX) if fast(args) else cap


def external_requests_cap(args) -> int:
    """At most how many requests to other sites the audit may send (DECISIONS 211), for its time estimate: 0 with
    --no-external-links (the at most 10 sameAs requests are in the estimate's fixed part), else the cap for a crawl
    that reads every page it may."""
    if getattr(args, "no_external_links", False):
        return 0
    defaults = CrawlConfig()
    ceiling = (min(defaults.external_link_checks_max, FAST_EXTERNAL_LINK_CHECKS_MAX) if fast(args)
               else defaults.external_link_checks_max)
    return external_link_cap(ceiling, defaults.external_link_checks_base, args.max_pages,
                             bool(getattr(args, "single_page", False)))


def _brand_family_domain(text: str) -> str:
    """One --brand-family-domain value: a host name and nothing else (no scheme, path, port or IP address)."""
    from .urls import clean_hostname

    host = clean_hostname(text)
    if host is None:
        raise argparse.ArgumentTypeError(f"not a domain name: {text[:80]!r} (write it like other-shop.example)")
    return host


def _business_type(value: str | None) -> str:
    from .business_types import profiles, valid
    value = (value or "auto").strip()
    if not valid(value):
        raise SystemExit(f"--business-type: unknown '{value}'; use auto or one of {', '.join(profiles())}")
    return value


def _crawl_config(args) -> CrawlConfig:
    """The audit settings for one `crawl` command line. `batch` builds each brand's settings through here too."""
    if getattr(args, "single_page", False):
        args.max_pages = 1  # also what the time limit and the reader's share are scaled to
    defaults = CrawlConfig()
    return CrawlConfig(
        max_pages=args.max_pages,
        single_page=bool(getattr(args, "single_page", False)),
        time_limit_s=_time_limit(args),
        reader_reserve_s=_reader_reserve(args),
        block_loopback=args.block_loopback,
        request_timeout_s=args.timeout,
        request_delay_s=args.delay,
        max_crawl_delay_s=args.max_crawl_delay,
        key_pages=tuple(args.key_page),
        business_type=_business_type(getattr(args, "business_type", "auto")),
        bot_info_url=args.bot_info_url,
        allowed_live_hosts=frozenset(args.allow_live_host),
        policy=DeclaredPolicy(training_bots=args.training_bots, search_bots=args.search_bots),
        intent_markings=_markings(args.intent_markings),
        site_verification_token=args.site_verification_token,
        site_verification_dns=args.verify_dns,
        probes_enabled=not args.no_probes,
        verification_enabled=not args.no_verification,
        robots_sample_interval_s=args.robots_sample_interval,
        access_logs=tuple(args.access_log),
        access_log_format=args.access_log_format,
        ip_range_files=tuple(args.ip_ranges),
        # Secrets come from the environment only, never from command-line arguments (shell history, ps).
        gsc_access_token=os.environ.get("MAYA_AUDIT_GSC_TOKEN") if args.gsc_site_url else None,
        gsc_site_url=args.gsc_site_url,
        bing_api_key=os.environ.get("MAYA_AUDIT_BING_API_KEY") if args.bing_site_url else None,
        bing_site_url=args.bing_site_url,
        indexnow_key=args.indexnow_key,
        indexnow_key_location=args.indexnow_key_location,
        render_enabled=not args.no_render,
        render_budget=render_budget(args),
        render_third_party=args.render_third_party,
        render_browser_channel=args.render_browser_channel,
        critical_facts=tuple(args.critical_fact),
        check_external_links=not getattr(args, "no_external_links", False),
        brand_family_domains=tuple(dict.fromkeys(getattr(args, "brand_family_domain", None) or [])),
        prf_enabled=not args.no_prf,
        soft_404_probe=not args.no_soft_404_probe,
        sitemap_check_max=sitemap_check_cap(args),
        fast_check=fast(args),
        **({"site_concurrency": args.site_concurrency} if getattr(args, "site_concurrency", None) is not None else {}),
        **({"llms_link_checks_max": min(defaults.llms_link_checks_max, FAST_LLMS_LINK_CHECKS_MAX),
            "image_checks_max": min(defaults.image_checks_max, FAST_IMAGE_CHECKS_MAX),
            "key_image_checks_max": min(defaults.key_image_checks_max, FAST_KEY_IMAGE_CHECKS_MAX),
            "external_link_checks_max": min(defaults.external_link_checks_max, FAST_EXTERNAL_LINK_CHECKS_MAX)}
           if fast(args) else {}),
        prf_round_gap_s=args.prf_round_gap,
        egress_region=args.egress_region,
        pagespeed_enabled=args.pagespeed,
        citations_file=args.citations,
        citation_domains_file=args.citation_domains,
        db_path=args.db_path,
        resume=args.resume,
        google_api_key=os.environ.get("MAYA_AUDIT_GOOGLE_API_KEY") if args.pagespeed else None,
    )


def _batch_command(args, parser: argparse.ArgumentParser) -> int:
    from . import batch

    def config_for(url: str) -> CrawlConfig:
        argv = ["crawl", url, "--max-pages", str(args.max_pages), "--delay", str(args.delay)]
        argv += ["--time-limit", str(args.time_limit)] if args.time_limit is not None else []
        argv += ["--no-render"] if args.no_render else []
        argv += ["--render-browser-channel", args.render_browser_channel] if args.render_browser_channel else []
        return _crawl_config(parser.parse_args(argv))

    args.open_firecrawl = None
    if not args.no_firecrawl:
        from . import firecrawl as fc
        from .firecrawl import settings as fc_settings

        if fc_settings.main_reader_on() and fc.load_key() is not None:
            def open_firecrawl(config: CrawlConfig):
                options = fc.Options(read_blocked=True, read_always=True, sitemap_discovery=True, max_pages=max(1, min(config.max_pages, fc_settings.MAX_PAGES_LIMIT)),
                                     allow_without_zero_data_retention=not fc_settings.zero_data_retention_wanted(),
                                     concurrency=fc_settings.concurrency())
                ledger, cache = fc.open_stores()
                return fc.FirecrawlClient(fc.load_key(), ledger, cache, approved_credits=options.estimate(config.max_pages)["max_credits"],
                                          max_pages=options.max_pages, proxy=options.proxy,
                                          allow_without_zero_data_retention=options.allow_without_zero_data_retention,
                                          resumed=bool(config.resume)), options

            args.open_firecrawl = open_firecrawl
    # Looked up at call time, so the audit a batch runs is whatever `crawl` runs.
    return batch.run(args, config_for, lambda url, config: run_audit(url, config))


def _tolerant_console() -> None:
    """Never let the console end an audit. On Windows a redirected stdout uses the ANSI code page, which cannot
    encode "→" or many page titles; printing the summary raised before the JSON and Markdown were written."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):  # not a TextIOWrapper (a test's capture, an embedded host)
            pass


def main(argv: list[str] | None = None) -> int:
    _tolerant_console()
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command in ("crawl", "batch"):
        # An audit keeps a Mac awake while it runs (DECISIONS 295); nothing is started elsewhere.
        from .keepawake import KeepAwake

        with KeepAwake():
            return _main(args, parser)
    return _main(args, parser)


def _main(args, parser: argparse.ArgumentParser) -> int:
    if args.command == "migrate-report":
        return _migrate(args.report, args.output)
    if args.command == "brief-check":
        from .ai_skills.check_output import main as brief_check_main
        return brief_check_main(args.argv)
    if args.command == "dfs":
        return _dfs_command(args)
    if getattr(args, "dfs_daily_budget", "absent") is None:
        from .dataforseo import pricing as dfs_pricing

        args.dfs_daily_budget = dfs_pricing.daily_budget()
    if args.command == "batch":
        return _batch_command(args, parser)
    if getattr(args, "single_page", False):
        args.max_pages = 1  # one page: the Firecrawl plan and the time limit are sized for it too
    dfs_client = dfs_plan = None
    if args.dataforseo or args.dfs_dry_run or args.dfs_search_data:
        code, dfs_client, dfs_plan = _dfs_prepare(args)
        if code is not None:
            return code
    fc_client = fc_options = fc_info = None
    fc_pages: list = []
    named = args.firecrawl or args.firecrawl_dry_run or args.firecrawl_render
    if named and args.no_firecrawl:
        parser.error("--no-firecrawl cannot be combined with the other --firecrawl options")
    automatic = False
    if not named and not args.no_firecrawl:
        from .firecrawl import settings as fc_settings

        automatic = fc_settings.main_reader_on() and fc_settings.load_key() is not None
    if named or automatic:
        code, fc_client, fc_options = _firecrawl_prepare(args, automatic)
        if code is not None:
            if dfs_client is not None:
                dfs_client.close()
            return code
    args.reader_planned = fc_client is not None
    output_error = _output_preflight(args)
    if output_error:
        print(f"error: {output_error}", file=sys.stderr)
        return 2
    config = _crawl_config(args)
    from . import evidence_store

    evidence_dir = (Path(args.evidence_dir).expanduser() if args.evidence_dir
                    else evidence_store.default_folder(args.url, args.json_path))
    wants_evidence = args.save_evidence == "all" or (args.save_evidence == "key" and config.key_pages)
    if wants_evidence and evidence_store.folder_in_use(evidence_dir) and not args.overwrite:
        print(f"error: the evidence folder already holds files: {evidence_dir}; choose another with --evidence-dir, "
              "pass --overwrite, or --save-evidence none", file=sys.stderr)
        return 2
    # The page reader starts the moment Maya's crawl ends, beside Maya's own later steps (DECISIONS 294), unless a paid
    # panel's ranking pages are still to come (then it reads after the audit, as before).
    early = None
    if fc_client is not None and dfs_client is None:
        from .firecrawl.reader import EarlyReading

        early = EarlyReading(fc_client, fc_options)
    try:
        outcome = run_audit(args.url, config, **({"reader": early} if early is not None else {}))
    except NetworkPreflightFailed as exc:
        # Nothing was requested from the site and nothing was spent: there is no report and no finding.
        for client in (dfs_client, fc_client):
            if client is not None:
                client.close()
        print(f"error: {exc.message}\n       ({exc.detail.get('detail')})\n       No request was sent to the site, nothing was spent, "
              "and no report was written.", file=sys.stderr)
        return 2
    except (HostNotAllowed, BotInfoPageNotReady, ConcurrentCrawlError) as exc:
        if dfs_client is not None:
            dfs_client.close()
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # The steps that follow share the audit's deadline and pace: nothing new is sent once the time limit has passed.
    clock = for_outcome(outcome)
    if dfs_client is not None:
        dfs_client.deadline_mono = clock.deadline_mono
    dfs_panel = None
    ranking_urls = []
    if dfs_client is not None:
        from .dataforseo import panel, insights
        try:
            dfs_panel = panel.run_checks(dfs_plan, dfs_client, refresh=args.dfs_refresh)
            ranking_urls = insights.ranking_landing_pages(dfs_panel, outcome.result.origin,
                min(fc_options.max_pages, config.max_pages) if fc_options else config.max_pages)
        finally:
            dfs_client.close()
    if fc_client is not None:
        if early is None or not early.started:
            fc_client.clock = clock  # a reading that started early keeps the clock it reads with
        from .firecrawl import panel as fc_panel
        from .firecrawl import reader as fc_reader

        try:  # after Maya's own crawl, which stays the access test; before anything is printed or written
            fc_raw = fc_reader.apply(outcome, config, fc_client, fc_options, ranking_urls=ranking_urls, early=early)
            fc_pages = fc_raw.get("view_pages") or []
            fc_info = fc_panel.section(fc_raw)
        finally:
            fc_client.close()
    print(render_text(outcome.result, outcome.gates, outcome.checks, firecrawl=fc_info))
    if fc_info is not None:
        print(fc_panel.render_text(fc_info))
    archive_info = crux_info = allow_steps = None
    from .firecrawl.reader import crawl_was_blocked

    if crawl_was_blocked(outcome.result, config)[0] and not (fc_info or {}).get("used"):
        # Nothing could read the site: the steps its owner can take, and archived copies when asked for.
        from . import allowlist
        from .classify import describe_blockers, identify_blocker

        named = describe_blockers([b for b in (identify_blocker(p.status, p.headers, p.classification_evidence, p.fetch_class.value)
                                               for p in outcome.result.pages) if b])
        allow_steps = (config.product_token, outcome.result.user_agent, named[0]["name"] if named else None)
        print("\n".join(["=" * 78, *allowlist.lines(*allow_steps), ""]))
        if args.archives:
            from . import archives

            archive_info = archives.collect(outcome.result, config, wayback=True, common_crawl=True, clock=clock)
            print("\n".join(["=" * 78, *archives.lines(archive_info, samples=False), ""]))
    from . import crux

    if crux.load_key():
        crux_info = crux.collect(args.url, clock=clock)
        print("\n".join(["=" * 78, *crux.lines(crux_info), ""]))
    evidence_index = None
    if wants_evidence:
        evidence_index = evidence_store.save_evidence(outcome.result, config, evidence_dir, args.save_evidence)
        print(f"verification evidence for {len(evidence_index['pages'])} page(s) saved to {evidence_dir}"
              + (f" ({len(evidence_index['not_saved'])} not saved: limit reached)" if evidence_index["not_saved"] else ""))
    from . import brand as brand_module

    # The brand: --dfs-brand, else the site's own name, else the address in the site's words, else none (DECISIONS 201).
    audit_brand = brand_module.resolve(outcome.result, getattr(args, "dfs_brand", None), fc_pages or None)
    if dfs_panel is not None:
        if args.dfs_search_data:
            relevance_pages = insights.relevance_pages(fc_pages, outcome.result.pages)
            insights.apply_relevance(dfs_panel, brand=args.dfs_brand, domain=dfs_panel.get("target"),
                texts=insights.page_texts(relevance_pages), pages=relevance_pages, brand_info=audit_brand)
        print(panel.render_text(dfs_panel))
    if args.json_path or args.markdown_path or args.markdown_brief_path or args.llm_brief_path:
        from . import final  # one sealed result: the report, its gate and its full address lists (DECISIONS 280)
        whole_s, slept_s = clock.elapsed_s(), clock.slept_s()  # the whole job, and any time the computer slept (295)
        sealed = final.seal(outcome, firecrawl=fc_info, all_phases_s=whole_s, brand=audit_brand, slept_s=slept_s)
        report = sealed.report
        if evidence_index is not None:
            report["evidence_saved"] = {key: evidence_index[key] for key in ("mode", "total_bytes", "limits")} | {
                # Relative to the JSON report, or the folder's name: never this computer's path (D-07).
                "folder": evidence_store.shown_folder(evidence_dir, args.json_path),
                "pages": len(evidence_index["pages"]), "not_saved": len(evidence_index["not_saved"])}
        if dfs_panel is not None:
            report["dataforseo"] = dfs_panel
        if fc_info is not None:
            report["firecrawl"] = fc_info
        if archive_info is not None:
            report["archives"] = archive_info
        if crux_info is not None:
            report["crux"] = crux_info
    try:
        if args.json_path:
            write_json(report, args.json_path, args.overwrite)
            print(f"evidence report written to {args.json_path}")
            gate = report.get("release_gate") or {}
            if gate:
                print(f"release gate: {gate.get('decision')} ({len(gate.get('violations') or [])} violation(s); "
                      "see release_gate in the report)")
            # The report keeps 25 addresses per finding; the full lists go beside it, named after the report so two
            # reports in one folder never share (or mix up) one list. A client report reads it (DECISIONS 259).
            target = Path(args.json_path)
            companion = str(target.with_name(target.stem + ".affected-urls.json"))
            write_json(sealed.affected, companion, args.overwrite)
            print(f"full affected-address lists written to {companion}")
        if args.markdown_path:
            markdown = render_markdown(outcome.result, outcome.gates, outcome.checks, firecrawl=fc_info)
            from .report import duration_line
            # Only the sleep is added here: the command line's duration line keeps its wording (the web app's names the whole job).
            markdown = markdown.replace(duration_line(outcome.result, None), duration_line(outcome.result, None, slept_s), 1)
            markdown += final.cards_markdown(report)  # where each broken link is, from the sealed report
            if dfs_panel is not None:
                markdown += panel.render_markdown(dfs_panel)
            if fc_info is not None:
                markdown += fc_panel.render_markdown(fc_info)
            if allow_steps is not None:
                markdown += allowlist.markdown(*allow_steps)
            if archive_info is not None:
                markdown += archives.markdown(archive_info)
            if crux_info is not None:
                markdown += crux.markdown(crux_info)
            write_markdown(markdown, args.markdown_path, args.overwrite)
            print(f"readable Markdown report written to {args.markdown_path}")
        if args.markdown_brief_path:
            write_markdown(render_markdown_brief(outcome.result, outcome.gates, outcome.checks, firecrawl=fc_info),
                           args.markdown_brief_path, args.overwrite)
            print(f"short Markdown report written to {args.markdown_brief_path}")
        if args.llm_brief_path:
            brief = build_llm_brief(report, outcome.result, args.llm_skills)
            write_llm_brief(brief, args.llm_brief_path, args.overwrite)
            usable = [s["skill_name"] for s in brief["skills"] if s["prompt"]]
            skipped = [f"{s['skill_name']} (needs {', '.join(s['missing'])})" for s in brief["skills"] if not s["prompt"]]
            print(f"llm brief written to {args.llm_brief_path}: {len(usable)} skill(s) ready"
                  + (f"; not run: {'; '.join(skipped)}" if skipped else ""))
    except FileExistsError as exc:
        print(f"error: output already exists: {exc.filename}; choose a new path or pass --overwrite", file=sys.stderr)
        return 2
    return run_outcome(outcome.result, outcome.gates, fc_info)[0]

if __name__ == "__main__":
    raise SystemExit(main())
