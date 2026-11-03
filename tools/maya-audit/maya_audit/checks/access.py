"""ACC-1 to ACC-8: AI-engine access checks (spec §5 ACC).

Findings carry severity, confidence, and rationale as separate fields
(spec §2). For noindex, severity depends on whether the page is user-marked
important or listed in a sitemap; internal links alone do not prove that a
utility page should be indexed. Intent markings and the declared bot policy can
move a finding to Info, and the severity it would otherwise have is kept.
"""

from __future__ import annotations

import shlex
from collections import defaultdict
from urllib.parse import urlsplit

from ..access_data import AccessData, homepage_url, key_page_urls
from ..config import PRIVATE_PATH_SEGMENTS, UTILITY_PATH_SEGMENTS, CrawlConfig
from ..coverage import settle_all
from ..directives import META_NAMES, page_directives, unavailable_after
from ..directives import parse_directive_list as _parse_directive_list  # noqa: F401 (re-export)
from ..findings import CheckResult, Finding, Rationale, ReviewItem, Severity, scope_for
from ..html_links import is_html
from ..intent import marking_by_id, split_by_intent
from ..models import Confidence, CrawlResult, FetchClass
from ..registry import NOT_PROBED, REGISTRY, RETIRED_TOKENS, UNVERIFIED_PROBE_UA, VENDOR_SCOPES, by_role, entry
from ..robots import decide as robots_decide
from ..robots import failure_cause, select_groups
from ..urls import detect_templates, request_target

ROBOTS_ENGINES_NOTE = "Effect on bots is Inferred: assumes they follow RFC 9309 as their vendors document."
ACC4_CAVEAT = (
    "Maya sent these requests with each bot's user-agent string from Maya's own IP; they are not requests from "
    "the real bot. WAFs that verify bots by IP may block Maya's request while allowing the real bot (a false "
    "positive), or, rarely, the reverse. Confirm with server logs (ACC-5)."
)
FIREWALL_NOT_ASSESSED = "Firewall blocking was not assessed."
# ACC-4 on a site whose ownership is not verified: a browser and Googlebot's user agent only (DECISIONS 205, LG-77).
UA_CHECK_SUMMARY = ("Firewall blocking was only partly assessed: a browser and Googlebot's user agent were compared on {n} "
                    "URL(s), one request each. Other AI crawlers were not tested (ownership not verified).")
UA_CHECK_NOTE = ("Measured with a spoofed user agent from Maya's own address, not by Google, one request each and not "
                 "retried. Some firewalls refuse a fake Googlebot on purpose. Confirm in Google Search Console (Settings "
                 "→ Crawl stats, or URL Inspection → Test live URL).")
REFUSED_FIX = ("Check Google Search Console (Settings → Crawl stats, by response) for 403 or 429 answers to the real "
               "Googlebot. Maya's request came from Maya's own address, which a firewall may refuse on purpose as a fake "
               "Googlebot; change nothing unless the real Googlebot is refused too.")
# "refused" (403/429 to Googlebot's user agent from Maya's address) is a note (DECISIONS 290): a firewall that refuses a
# fake Googlebot on purpose answers exactly so, and a request from Maya cannot tell that from refusing Google.
UA_CHECK_SEVERITY = {"server_error": Severity.S2, "refused": Severity.INFO, "not_found_for_bot": Severity.S3,
                     "empty_for_bot": Severity.S3, "challenged": Severity.INFO, "size": Severity.INFO}
RETIRED_FIX = ("Write the same rules for the user agents Anthropic uses now: ClaudeBot for training, Claude-SearchBot for search and "
               "Claude-User for live fetches. The old lines can stay, but they do nothing.")
UNGROUPED_FIX = ("Move each listed line under the User-agent line it is meant for (for every crawler: under “User-agent: *”). "
                 "A rule above the first User-agent line belongs to no group, so no crawler applies it.")
GOOGLE = "Google AI Overviews / AI Mode"
COPILOT = "Microsoft Copilot (Bing index)"


# -- helpers -----------------------------------------------------------------

def _access(result: CrawlResult) -> AccessData:
    assert result.access is not None, "run the audit through maya_audit.audit.run_audit"
    return result.access


def _tier(urls, key_urls: set[str]) -> int:
    return 0 if any(u in key_urls for u in urls) else 2


def _curl(url: str, user_agent: str, probe: bool = False) -> str:
    header = " -H 'X-Maya-Probe: ua-differential'" if probe else ""
    return f"curl -i -A {shlex.quote(user_agent)}{header} {shlex.quote(url)}"


def _gates(tokens, probes: bool = False) -> list[str]:
    """Launch-gate reasons relevant to a finding. Probe user-agent strings only matter for ACC-4."""
    out = []
    for t in sorted(tokens):
        reasons = [r for r in entry(t).launch_gate if probes or r not in (UNVERIFIED_PROBE_UA, NOT_PROBED)]
        if reasons:
            out.append(f"{t}: {'; '.join(reasons)}")
    return out


def _with_intent(check_id, condition, items, severity, key_urls, cfg, build) -> list[Finding]:
    """Split (url, token) items by intent markings: unmarked keep `severity`, marked become Info."""
    unmarked, covered, excluded = split_by_intent(cfg.intent_markings, check_id, condition, items, key_urls)
    out = []
    if unmarked:
        finding = build(unmarked, severity, None)
        if excluded:
            finding.notes.append(
                f"{len(excluded)} key page(s) match an intent-marking pattern but are not covered: "
                "pattern markings never cover key pages (spec §2.5)."
            )
            finding.evidence["intent_marking_exclusions"] = excluded
        out.append(finding)
    for marking_id, marked_items in covered.items():
        marking = marking_by_id(cfg.intent_markings, marking_id)
        intent = {
            "kind": "intent_marking", "marking_id": marking.id, "scope": marking.scope, "token": marking.token,
            "marked_by": marking.marked_by, "marked_at": marking.marked_at, "note": marking.note,
            "severity_otherwise": severity.value,
        }
        out.append(build(marked_items, Severity.INFO, intent))
    return out


def private_path_segment(url: str, pattern: str = "") -> str | None:
    """The segment that marks `url` (or the robots.txt pattern that blocks it) as a private or technical path."""
    for path in (urlsplit(url).path, pattern.split("?", 1)[0].replace("*", "").replace("$", "")):
        for segment in path.lower().split("/"):
            name = segment.rsplit(".", 1)[0] if "." in segment else segment
            if name in PRIVATE_PATH_SEGMENTS:
                return name
    return None


def utility_path_segment(url: str) -> str | None:
    """The segment that marks `url` as a utility page (a QR menu, a print page, ...: ACC-3, DECISIONS 222)."""
    for segment in urlsplit(url).path.lower().split("/"):
        name = segment.rsplit(".", 1)[0] if "." in segment else segment
        if name in UTILITY_PATH_SEGMENTS:
            return name
    return None


# ACC-3: noindex on a utility page the menu does not link (DECISIONS 222).
UTILITY_NOINDEX_TITLE = ("noindex via {where} on {n} utility page(s) (such as a QR menu or a print page): check that this "
                         "is intended")
UTILITY_NOINDEX_FIX = ("If this page should appear in search and AI answers, remove the noindex. A QR menu, print or "
                       "thank-you page is usually left out on purpose; then mark it as intended.")
# ACC-3 (H26, CR-33): noindex on a page the sitemap lists. The owner's intent is not known (the sitemap may simply list
# every page), so the noindex is S3. Review G16: the sitemap listing it is the same fact, said in that one finding (its
# title names both, its advice covers both); the separate S2 "the sitemap lists N noindex pages" is gone. Many CMSs put
# noindex pages in the sitemap on their own, so it is not High. SITEMAP_NOINDEX_TITLE stays for the wording catalogue.
LISTED_NOINDEX_TITLE = "{label} on {n} page(s) the sitemap lists: check that this is intended"
SITEMAP_NOINDEX_TITLE = "The sitemap lists {n} page(s) that carry noindex"
SITEMAP_NOINDEX_FIX = ("Take these pages out of the sitemap if they are meant to stay out of search, or remove the noindex "
                       "if they are meant to be found. A sitemap should list only pages you want indexed.")
SITEMAP_NOINDEX_EXPECTED = "the sitemap lists only pages that may be indexed"
LISTED_NOINDEX_FIX = ("If these pages should appear in search and AI answers, remove the directive. If it is deliberate, "
                      "mark it as intended and take the pages out of the sitemap.")


def _should_be_indexed(result: CrawlResult, cfg: CrawlConfig) -> dict[str, str]:
    """URLs the site itself presents as pages to find, and how: the homepage, key pages, the sitemap, the navigation."""
    reasons: dict[str, str] = {}
    for page in result.pages:
        for edge in page.outlinks or []:
            if edge.get("nav"):
                reasons[edge["target"]] = "linked from the navigation"
    reasons.update({url: "listed in the sitemap" for url in result.sitemap_urls})
    reasons.update({url: "a key page" for url in key_page_urls(result, cfg)})
    reasons[homepage_url(result)] = "the homepage"
    return reasons


def _status(findings, review_items=()) -> str:
    if findings:
        return "findings"
    return "needs_review" if review_items else "pass"


# -- ACC-1 -------------------------------------------------------------------

def acc1_robots_availability(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "robots.txt availability"
    access = _access(result)
    samples = access.robots_samples
    robots_url = f"{result.origin}/robots.txt"
    # Only an answer the site sent can be the site's failure. A fetch that got no answer (a DNS lookup that failed on
    # this computer, a timeout, a refused connection) is not checked, and is never a finding.
    failed = [s for s in samples if s["status"] is not None and s["status"] >= 500]
    unanswered = [s for s in samples if s["error"] or s["status"] is None]
    local = [s for s in unanswered if failure_cause(s["error"]) == "local_network"]
    ok = [s for s in samples if s["status"] is not None and 200 <= s["status"] < 300]
    engines = sorted({e.engine for e in REGISTRY if e.role in ("search", "training")})
    per_bot = (
        "compared in ACC-4 (ownership verified)" if access.ownership["verified"]
        else "not done: ownership not verified, so robots.txt was fetched only with Maya's user agent"
    )
    evidence = {
        "robots_url": robots_url,
        "samples": samples,
        "sample_interval_s": cfg.robots_sample_interval_s,
        "per_bot_user_agent_fetches": per_bot,
        "reproduce": _curl(robots_url, cfg.user_agent),
    }
    findings: list[Finding] = []
    observations: list[dict] = []

    if failed:
        statuses = [s["status"] if s["status"] is not None else s["error"] for s in samples]
        findings.append(Finding(
            "ACC-1", f"robots.txt returned a server error on {len(failed)} of {len(samples)} fetches",
            Severity.S1, Confidence.VERIFIED, "Documented (RFC 9309, vendor robots.txt docs)", engines,
            scope_for([robots_url], sitewide=True), {**evidence, "statuses_in_order": statuses},
            "robots.txt answers 200 (or 404 if there are no rules) on every fetch",
            "Make /robots.txt reliably return 200, or 404 if you have no rules. Under RFC 9309 a 5xx "
            "robots.txt means compliant crawlers assume the whole site is disallowed, even if it happens only sometimes.",
            notes=[ROBOTS_ENGINES_NOTE],
        ))
    if any(s["over_500_kib"] for s in ok):
        findings.append(Finding(
            "ACC-1", "robots.txt is larger than 500 KiB", Severity.S3, Confidence.VERIFIED,
            "Documented (RFC 9309 lets parsers ignore content past 500 KiB)", engines,
            scope_for([robots_url], sitewide=True), evidence, "robots.txt under 500 KiB",
            "Shrink robots.txt below 500 KiB. Rules past that point may be ignored.", notes=[ROBOTS_ENGINES_NOTE],
        ))
    if any(s["looks_like_html"] for s in ok):
        findings.append(Finding(
            "ACC-1", "robots.txt returns an HTML page", Severity.INFO, Confidence.VERIFIED,
            "Documented (RFC 9309)", engines, scope_for([robots_url], sitewide=True), evidence,
            "a plain-text robots.txt, or a 404",
            "An HTML page parses as an empty robots.txt, which allows everything. That is usually harmless; serve "
            "plain text if you intend to set rules.",
        ))
    # A rule above the first User-agent line belongs to no group (RFC 9309 §2.1): the owner wrote a rule that no crawler
    # applies, usually meaning it for every crawler. Read from the crawl's own parse of the file (H17).
    parsed = result.robots_policy_by_origin.get(result.origin)
    ungrouped = list(getattr(getattr(parsed, "robots", None), "ungrouped", None) or [])
    if ungrouped:
        findings.append(Finding(
            "ACC-1", f"{len(ungrouped)} robots.txt rule(s) come before any User-agent line, so no crawler applies them",
            Severity.S4, Confidence.VERIFIED, "Documented (RFC 9309 §2.1: a rule belongs to the group above it)", engines,
            scope_for([robots_url], sitewide=True),
            {**evidence, "ungrouped_lines": [{"line": n, "text": text} for n, text in ungrouped[:40]],
             "reproduce": f"curl -s {shlex.quote(robots_url)} | sed -n '{ungrouped[0][0]}p'"},
            "every rule in robots.txt sits under a User-agent line",
            UNGROUPED_FIX, notes=[ROBOTS_ENGINES_NOTE],
        ))
    for s in samples:
        if s["status"] == 429:
            observations.append({
                "metric": "robots.txt answered 429", "attempt": s["attempt"],
                "note": "RFC 9309 classes 4xx as 'unavailable' (crawling allowed), but Maya stops on a 429. How AI "
                        "bots treat a 429 robots.txt is not determined.",
            })

    if unanswered:
        why = ("network problem on this computer" if len(local) == len(unanswered)
               else "no answer reached this computer; whether the site or the connection failed is not known")
        evidence["not_checked"] = {"fetches": len(unanswered), "of": len(samples), "why": why,
                                   "errors": sorted({str(s["error"]) for s in unanswered})[:5]}
        observations.append({"metric": "robots.txt fetches with no answer", "value": len(unanswered), "of": len(samples),
                             "note": f"Not checked ({why}). This is not a finding about the site."})
    answered = [s for s in samples if s not in unanswered]
    if unanswered and not answered:
        policy = result.robots_policy_by_origin.get(result.origin)
        if policy is not None:
            evidence["applied_policy"] = {"source": "Maya's own crawler", "status": policy.status, "mode": policy.mode, "reason": policy.reason}
        return CheckResult("ACC-1", title, "not_assessed",
                           f"Not checked ({why}): none of {len(samples)} robots.txt fetch(es) got an answer. "
                           "Nothing is reported against the site.", [], evidence, observations)
    if findings:
        summary = f"{len(findings)} finding(s) from {len(samples)} robots.txt fetches."
    else:
        samples = answered
        statuses = sorted({s["status"] for s in samples})
        meaning = (
            "rate limited: back off and retry later" if any(s["status"] == 429 for s in samples) else
            "RFC 9309 treats 4xx as no restrictions" if all(400 <= (s["status"] or 0) < 500 for s in samples)
            else "parsed normally"
        )
        summary = f"robots.txt answered {statuses} on all {len(samples)} fetches ({meaning})."
    policy = result.robots_policy_by_origin.get(result.origin)
    if policy is not None:
        evidence["applied_policy"] = {"source": "Maya's own crawler", "status": policy.status,
                                      "mode": policy.mode, "reason": policy.reason}
        summary += f" Applied policy: {policy.reason}."
    if unanswered:
        summary += f" {len(unanswered)} other fetch(es) got no answer and were not checked ({why})."
    return CheckResult("ACC-1", title, _status(findings), summary, findings, evidence, observations)


# -- ACC-2 -------------------------------------------------------------------

def _role_how_to_fix(role: str, engines: list[str], line: int) -> str:
    if role == "search":
        return (f"If {', '.join(engines)} should be able to find and cite these pages, remove or narrow the rule "
                f"on line {line} for these user agents. If blocking them is deliberate, mark it as intended.")
    if role == "live":
        return (f"Live fetchers may not follow robots.txt at all (see ACC-4 for what they actually receive). "
                f"If you want users' AI assistants to read these pages, remove the rule on line {line}.")
    # What these tokens are used for comes from the registry (B14): "not live AI answers" was wrong for Google-Extended,
    # which Google documents as the control for Gemini's grounding too.
    return (f"These user agents serve: {'; '.join(engines)}. If blocking them matches your policy, record it in the declared "
            f"bot policy; otherwise change line {line}.")


def _acc2_role_findings(findings: list, role: str, items: list, search_severity: Severity, build, key_urls, cfg) -> None:
    """One blocked rule's findings for one bot role, with the declared policy and intent markings applied."""
    if role == "search":
        if cfg.policy.search_bots == "block":
            findings.append(build(items, Severity.INFO, {"kind": "declared_policy", "policy": "search_bots=block",
                                                          "severity_otherwise": search_severity.value}))
        else:
            findings.extend(_with_intent("ACC-2", "disallow", items, search_severity, key_urls, cfg, build))
    elif role == "live":
        findings.extend(_with_intent("ACC-2", "disallow", items, Severity.S3, key_urls, cfg, build))
    elif cfg.policy.training_bots == "block":
        findings.append(build(items, Severity.INFO, {"kind": "declared_policy", "policy": "training_bots=block",
                                                      "severity_otherwise": Severity.S4.value}))
    else:
        f = build(items, Severity.S4, None)
        if cfg.policy.training_bots == "allow":
            f.notes.append("Policy mismatch: the declared policy allows training bots, but robots.txt blocks them.")
            f.evidence["policy_mismatch"] = True
        findings.append(f)


def acc2_robots_rules(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "robots.txt rules per AI user agent"
    access = _access(result)
    policy = result.robots_policy_by_origin[result.origin]
    robots_url = f"{result.origin}/robots.txt"
    sample = [s["url"] for s in access.url_sample]
    why = {s["url"]: s["why"] for s in access.url_sample}
    key_urls = set(key_page_urls(result, cfg))

    if policy.mode == "not_checked":
        return CheckResult("ACC-2", title, "not_assessed", f"Not checked: {policy.reason}.", evidence={"robots_mode": policy.mode})
    if policy.mode == "disallow_all":
        return CheckResult("ACC-2", title, "not_assessed",
                           f"robots.txt unavailable ({policy.reason}); ACC-1 reports the sitewide block.",
                           evidence={"robots_mode": policy.mode})

    decisions = {e.token: {u: policy.decide(e.token, u) for u in sample} for e in REGISTRY}
    matrix = {
        e.token: {
            "role": e.role,
            "allowed": sum(d.allowed for d in decisions[e.token].values()),
            "disallowed": sum(not d.allowed for d in decisions[e.token].values()),
            "group": next(iter(decisions[e.token].values())).group_kind if sample else None,
        }
        for e in REGISTRY
    }
    evidence = {"robots_url": robots_url, "robots_mode": policy.mode, "url_sample": access.url_sample,
                "matrix": matrix, "declared_policy": {"training_bots": cfg.policy.training_bots,
                                                      "search_bots": cfg.policy.search_bots}}
    if policy.mode == "allow_all":
        return CheckResult("ACC-2", title, "pass",
                           f"robots.txt returned {policy.status}: RFC 9309 treats this as no restrictions for any bot.",
                           evidence=evidence)

    findings: list[Finding] = []
    indexed = _should_be_indexed(result, cfg)
    base_severity = {"search": Severity.S1, "live": Severity.S3, "training": Severity.S4}
    for role in ("search", "live", "training"):
        blocked: dict[tuple, list[tuple[str, str]]] = defaultdict(list)
        for bot in by_role(role):
            for url, d in decisions[bot.token].items():
                if not d.allowed and d.rule is not None:
                    blocked[(d.rule.line, d.rule.pattern, d.group_kind)].append((url, bot.token))

        for (line, pattern, group_kind), all_items in sorted(blocked.items()):
            def build(its, severity, intent, line=line, pattern=pattern, group_kind=group_kind, role=role):
                tokens = sorted({t for _, t in its})
                urls = sorted({u for u, _ in its})
                engines = sorted({entry(t).engine for t in tokens})
                notes = [ROBOTS_ENGINES_NOTE]
                sitewide = pattern.strip() == "/"
                if sitewide:
                    notes.append("This Disallow rule covers the whole site, beyond the sampled URLs shown here.")
                if role == "live":
                    notes.append("robots.txt may not apply to live fetchers; ACC-4 checks what they actually receive.")
                return Finding(
                    "ACC-2",
                    f"robots.txt line {line} (Disallow: {pattern}) blocks {role} bot(s) {', '.join(tokens)} "
                    + ("sitewide" if pattern.strip() == "/" else f"on {len(urls)} sampled URL(s)"),
                    severity, Confidence.VERIFIED, Rationale.DOCUMENTED.value, engines,
                    ({"kind": "sitewide", "count": len(urls), "urls": urls[:40]} if sitewide else scope_for(urls)),
                    {
                        "robots_url": robots_url,
                        "rule": {"line": line, "directive": "disallow", "pattern": pattern},
                        "group": group_kind,
                        "decisions": [{"url": u, "token": t, "reason": decisions[t][u].reason,
                                       "user_agent_lines": list(decisions[t][u].group_lines)} for u, t in its[:40]],
                        "sampled_because": {u: why.get(u) for u in urls},
                        # The tokens this rule blocks: what ANS-4 reads to point at this finding (B13).
                        "blocked_tokens": tokens,
                        "bot_provenance": {t: entry(t).provenance() for t in tokens},
                        "reproduce": f"curl -s {shlex.quote(robots_url)} | sed -n '{line}p'",
                    },
                    "search bots can fetch pages meant to be cited" if role == "search" else "matches the site owner's policy",
                    _role_how_to_fix(role, engines, line),
                    intent=intent, launch_gated=_gates(tokens), notes=notes, importance_tier=_tier(urls, key_urls),
                )

            # What a blocked URL is decides how much the block matters. A rule over the whole site, or over a URL
            # the site itself puts forward (homepage, key page, sitemap, navigation), keeps the role's severity. A
            # rule that only reaches private or technical paths (checkout, login, /cdn-cgi/) is housekeeping: Info.
            # Anything else is a real page the site does not put forward, so a search-bot block there is S3, not S1.
            sitewide_rule = pattern.strip() == "/"
            # A cart or login link sits in most sites' navigation; that alone does not make it a page to be found.
            put_forward = [(u, t) for u, t in all_items if sitewide_rule or (u in indexed and not (
                indexed[u] == "linked from the navigation" and private_path_segment(u, pattern)))]
            private = [(u, t) for u, t in all_items if (u, t) not in put_forward and private_path_segment(u, pattern)]
            other = [(u, t) for u, t in all_items if (u, t) not in put_forward and (u, t) not in private]
            if private:
                finding = build(private, Severity.INFO, {"kind": "private_or_technical_path",
                                                         "severity_otherwise": base_severity[role].value})
                matched = sorted({private_path_segment(u, pattern) for u, _ in private})
                finding.notes.append(
                    f"Reported as Info: the blocked path is a private or technical one ({', '.join(matched)}), which sites "
                    "normally keep bots out of, and none of the blocked URLs is the homepage, a key page or listed in the sitemap.")
                finding.evidence["path_kind"] = {"kind": "private_or_technical", "matched_segments": matched}
                findings.append(finding)
            for items, search_severity, kind in ((put_forward, Severity.S1, "put_forward"), (other, Severity.S3, "other")):
                if not items:
                    continue
                before = len(findings)
                _acc2_role_findings(findings, role, items, search_severity, build, key_urls, cfg)
                for finding in findings[before:]:
                    urls = sorted({u for u, _ in items})
                    if kind == "put_forward":
                        finding.evidence["path_kind"] = {"kind": "pages_meant_to_be_found", "why": {
                            u: "the rule covers the whole site" if sitewide_rule else indexed[u] for u in urls}}
                    else:
                        finding.evidence["path_kind"] = {"kind": "not_put_forward"}
                        if role == "search":
                            finding.notes.append(
                                "S3 rather than S1: none of the blocked URLs is the homepage, a key page, listed in the "
                                "sitemap or linked from the navigation, so the site does not itself put them forward.")

    # Reverse mismatches: the declared policy says block, but robots.txt allows.
    for role, declared in (("training", cfg.policy.training_bots), ("search", cfg.policy.search_bots)):
        if declared != "block":
            continue
        allowed = sorted(t for t, m in matrix.items() if m["role"] == role and m["allowed"] > 0)
        if allowed:
            findings.append(Finding(
                "ACC-2", f"Policy mismatch: declared policy blocks {role} bots, but robots.txt allows "
                         f"{', '.join(allowed)} on at least one sampled URL",
                Severity.INFO, Confidence.VERIFIED, Rationale.DOCUMENTED.value,
                sorted({entry(t).engine for t in allowed}), scope_for(sample, sitewide=True),
                {"robots_url": robots_url, "allowed_tokens": {t: matrix[t] for t in allowed}, "blocked_tokens": []},
                f"robots.txt blocks {role} bots, as declared",
                f"Add Disallow rules for these user agents, or change the declared {role}-bot policy.",
                launch_gated=_gates(allowed),
            ))

    # Group precedence (RFC 9309): a bot with its own group ignores every * rule.
    if policy.robots is not None:
        unblocked: dict[int, set[tuple[str, str]]] = defaultdict(set)
        for bot in REGISTRY:
            if select_groups(policy.robots, bot.token)[1] != "specific":
                continue
            for url in sample:
                star = robots_decide(policy.robots, "*", url)
                if not star.allowed and star.rule and decisions[bot.token][url].allowed:
                    unblocked[star.rule.line].add((url, bot.token))
        for line, items in sorted(unblocked.items()):
            tokens = sorted({t for _, t in items})
            urls = sorted({u for u, _ in items})
            findings.append(Finding(
                "ACC-2", f"Group precedence: {', '.join(tokens)} have their own robots.txt group, so the * rule on "
                         f"line {line} does not apply to them",
                Severity.INFO, Confidence.VERIFIED, Rationale.DOCUMENTED.value,
                sorted({entry(t).engine for t in tokens}), scope_for(urls),
                {"robots_url": robots_url, "star_rule_line": line, "urls": urls, "blocked_tokens": [],
                 "reproduce": f"curl -s {shlex.quote(robots_url)}"},
                "rules meant for all bots are repeated in each bot-specific group",
                f"Under RFC 9309 a bot obeys only its most specific group. If line {line} should also apply to "
                f"{', '.join(tokens)}, repeat it inside their group.",
                launch_gated=_gates(tokens), importance_tier=_tier(urls, key_urls),
            ))

    # Rules for user agents that are no longer used (B14): the owner may believe they block something.
    if policy.robots is not None:
        retired = sorted({(token, line) for g in policy.robots.groups for token, line in g.agents if token in RETIRED_TOKENS})
        if retired:
            names = sorted({t for t, _ in retired})
            findings.append(Finding(
                "ACC-2", f"robots.txt has rules for {', '.join(names)}, which no longer have any effect",
                Severity.INFO, Confidence.VERIFIED, Rationale.DOCUMENTED.value, ["Claude (Anthropic)"],
                scope_for([robots_url], sitewide=True),
                {"robots_url": robots_url, "retired_tokens": [{"token": t, "line": n, "why": RETIRED_TOKENS[t]} for t, n in retired],
                 "blocked_tokens": []},
                "robots.txt names the user agents the vendors use today",
                RETIRED_FIX, launch_gated=_gates(["ClaudeBot"])))

    if findings:
        worst = min(findings, key=lambda f: ["S1", "S2", "S3", "S4", "Info"].index(f.severity.value))
        summary = f"{len(findings)} finding(s); most severe: [{worst.severity.value}] {worst.title}"
    else:
        summary = f"All {len(REGISTRY)} registry bots may fetch all {len(sample)} sampled URLs."
    return CheckResult("ACC-2", title, _status(findings), summary, findings, evidence)


# -- ACC-3 -------------------------------------------------------------------

# ACC-3 (DECISIONS 300, the owner's review of the nihan report): the site's own search results and cart are utility
# pages a search engine should not index. One that answers 200 with no noindex (meta robots or X-Robots-Tag, for all
# crawlers or Googlebot) and no canonical to another address is a Low finding. The last path segment decides
# (`/search`, `/en/cart`, `/arama?q=`), never a segment further up (`/search-tips/...`).
INDEXABLE_UTILITY_SEGMENTS = frozenset({"search", "arama", "ara", "cart", "sepet", "sepetim", "basket"})
UTILITY_INDEXABLE_EXPECTED = "internal search and cart pages carry noindex"
UTILITY_INDEXABLE_FIX = ("Add a noindex robots meta tag to the internal search and cart pages and keep them out of the "
                         "sitemap; on Shopify, add it in the theme's <head> for the search and cart templates.")


def indexable_utility_page(page) -> str | None:
    """The segment (`search`, `cart`, ...) when `page` is the site's search or cart page and may be indexed."""
    if page.analysis is None or page.status is None or not 200 <= page.status < 300:
        return None
    segments = [s for s in urlsplit(page.url).path.lower().split("/") if s]
    last = segments[-1].rsplit(".", 1)[0] if segments else ""
    if last not in INDEXABLE_UTILITY_SEGMENTS:
        return None
    for d in page_directives(page):
        if d["directive"] in ("noindex", "none") and d["scope"] in ("*", "googlebot"):
            return None
    own = page.url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    for canonical in (page.analysis or {}).get("canonicals") or []:
        if isinstance(canonical, str) and canonical.split("?", 1)[0].rstrip("/") != own:
            return None
    return last


def utility_indexable_findings(pages, key_urls: set[str], user_agent: str) -> list[Finding]:
    found = {p.url: seg for p in pages if (seg := indexable_utility_page(p))}
    if not found:
        return []
    urls = list(found)
    return [Finding("ACC-3", f"{len(urls)} internal search or cart page(s) can be indexed (no noindex)",
        Severity.S4, Confidence.VERIFIED,
        "Documented (Google: internal search result pages)", [GOOGLE, COPILOT], scope_for(urls),
        {"pages": [{"url": u, "segment": found[u], "noindex": False} for u in urls[:40]],
         "rule": "the last path segment is the site's search or cart page; no noindex; no canonical to another address",
         "reproduce": [f"{_curl(u, user_agent)} | grep -i -E 'robots|canonical'" for u in urls[:3]]},
        UTILITY_INDEXABLE_EXPECTED, UTILITY_INDEXABLE_FIX, importance_tier=_tier(urls, key_urls))]


def acc3_page_controls(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Page-level AI controls (meta robots, X-Robots-Tag, snippet controls)"
    key_urls = set(key_page_urls(result, cfg))
    sitemap_urls = set(result.sitemap_urls)
    pages = [p for p in result.pages if p.content_checks_eligible and p.analysis is not None]
    # Non-HTML documents the crawl fetched (PDFs, for example) are cited too, and can only be withheld from an
    # index by the X-Robots-Tag header, so their headers are checked as well.
    documents = [p for p in result.pages if p.content_checks_eligible and p.analysis is None
                 and p.status is not None and 200 <= p.status < 300]
    groups: dict[tuple, dict] = {}
    # Pages the site's navigation links to (an edge marked nav): a utility page there is put forward (DECISIONS 222).
    in_navigation = {edge["target"] for p in result.pages for edge in (p.outlinks or []) if edge.get("nav")}
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    def add(condition, label, severity, engines, confidence, rationale, gated, page, raw):
        key = (condition, label)
        g = groups.setdefault(key, {"severity": severity, "engines": engines, "confidence": confidence,
                                    "rationale": rationale, "gated": gated, "pages": {}})
        g["pages"].setdefault(page.url, []).append(raw)

    for page in pages + documents:
        for d in page_directives(page):
            scope, directive, value, raw = d["scope"], d["directive"], d["value"], d["raw"]
            where = f"{d['source']}" + ("" if scope == "*" else f" ({scope})")
            google = scope in ("*", "googlebot")
            bing = scope in ("*", "bingbot")
            # unavailable_after (B06): Google drops the page after that moment. A date that has passed works like noindex
            # for Google; one still to come is a note. An unreadable date is left to the person (it is in the evidence).
            passed = None
            if directive == "unavailable_after" and google:
                when = unavailable_after(value)
                if when is not None:
                    passed = when <= now
                    if not passed:
                        add("unavailable_after_future", f"unavailable_after {value} via {where}", Severity.INFO, [GOOGLE],
                            Confidence.VERIFIED, "Documented (Google)", [], page, raw)
            if directive in ("noindex", "none") or passed:
                engines = ([GOOGLE] if google else []) + ([COPILOT] if bing and not passed else [])
                if passed:
                    where = f"unavailable_after (date passed) via {where}"
                if engines:
                    if scope == "*":
                        engines.append("other engines: undocumented (Inferred)")
                    # Internal links may come from utility navigation (cart, login,
                    # search), so they do not establish that a page should be indexed.
                    is_important = page.url in key_urls or page.url in sitemap_urls
                    # A utility page (a QR menu, a print page) in the sitemap, not a key page and not in the menu: a
                    # note to check, not a Blocker (DECISIONS 222).
                    utility = (not passed and is_important and page.url not in key_urls and page.url not in in_navigation
                               and utility_path_segment(page.url) is not None)
                    if utility:
                        add("noindex_utility", where, Severity.S3, engines, Confidence.VERIFIED,
                            "Documented (Google, Bing) / Hypothesis (others)", [], page, raw)
                        continue
                    what = where if passed else f"noindex via {where}"
                    # A key page (the owner marked it important), or a sitemap page the menu also links (DECISIONS 222:
                    # the site puts it forward twice): S1, as before.
                    if page.url in key_urls or (is_important and page.url in in_navigation):
                        add("noindex", what, Severity.S1, engines, Confidence.VERIFIED,
                            "Documented (Google, Bing) / Hypothesis (others)", [], page, raw)
                    elif is_important:  # listed in the sitemap only: intent unknown (H26, CR-33)
                        add("noindex_listed", what, Severity.S3, engines, Confidence.VERIFIED,
                            "Documented (Google, Bing) / Hypothesis (others)", [], page, raw)
                    else:
                        add("noindex", f"{what} (page intent should be reviewed)", Severity.INFO, engines, Confidence.VERIFIED,
                            "Documented (Google, Bing) / Hypothesis (others)", [], page, raw)
            if google and directive in ("nosnippet", "none"):
                add("nosnippet", f"nosnippet via {where}", Severity.S1, [GOOGLE], Confidence.VERIFIED,
                    "Documented (Google)", [], page, raw)
            if google and directive == "max-snippet" and value is not None:
                try:
                    n = int(value)
                except ValueError:
                    continue
                if n == 0:
                    add("max-snippet", f"max-snippet:0 via {where}", Severity.S1, [GOOGLE], Confidence.VERIFIED,
                        "Documented (Google)", [], page, raw)
                elif 0 < n < cfg.min_max_snippet:
                    add("max-snippet", f"max-snippet below {cfg.min_max_snippet} via {where}", Severity.S2, [GOOGLE],
                        Confidence.VERIFIED, "Documented (Google)", [], page, raw)
            if bing and directive == "noarchive":
                add("noarchive", f"noarchive via {where}", Severity.S2, [COPILOT], Confidence.VERIFIED,
                    "Documented (Bing Webmaster Blog, 2023; not re-verified)",
                    ["Bing noarchive/nocache controls not re-verified (spec §4 launch gate)"], page, raw)
            if bing and directive == "nocache":
                add("nocache", f"nocache via {where}", Severity.INFO, [COPILOT], Confidence.VERIFIED,
                    "Documented (Bing Webmaster Blog, 2023; not re-verified)",
                    ["Bing noarchive/nocache controls not re-verified (spec §4 launch gate)"], page, raw)

        a = page.analysis
        if a is None:
            continue  # data-nosnippet is an HTML attribute; nothing to measure in a non-HTML document
        region_chars = a["main_region_chars"] if a["has_main_region"] and a["main_region_chars"] else a["visible_chars"]
        covered = a["main_region_nosnippet_chars"] if a["has_main_region"] and a["main_region_chars"] else a["data_nosnippet_chars"]
        if region_chars and covered / region_chars >= cfg.data_nosnippet_share:
            region = "<main>/<article>" if a["has_main_region"] and a["main_region_chars"] else "whole body (no <main> or <article>)"
            add("data-nosnippet", "main content inside data-nosnippet", Severity.S2, [GOOGLE],
                Confidence.VERIFIED if a["has_main_region"] else Confidence.ESTIMATED, "Documented (Google)", [], page,
                f"{covered}/{region_chars} visible characters of the {region} are inside data-nosnippet elements")

    findings: list[Finding] = []
    for (condition, label), g in groups.items():
        items = [(url, None) for url in g["pages"]]

        def build(its, severity, intent, g=g, label=label, condition=condition):
            urls = [u for u, _ in its]
            utility = condition == "noindex_utility"
            listed = condition == "noindex_listed"
            return Finding(
                "ACC-3", f"{label} on {len(urls)} page(s)" if not (utility or listed) else (
                    UTILITY_NOINDEX_TITLE.format(where=label, n=len(urls)) if utility else
                    LISTED_NOINDEX_TITLE.format(label=label, n=len(urls))),
                severity, g["confidence"], g["rationale"], g["engines"],
                scope_for(urls),
                {"directives": {u: g["pages"][u] for u in urls[:40]},
                 **({"utility_segments": {u: utility_path_segment(u) for u in urls[:40]},
                     "rule": "a utility path, listed in the sitemap, not a key page and not linked from the navigation"}
                    if utility else {}),
                 # Review G16: the sitemap listing a noindex page is the same fact seen from the sitemap, said here
                 # once (S3), not as a second finding above the directive itself.
                 **({"listed_in_sitemaps": [d.url for d in result.sitemap_docs][:10],
                     "sitemap_side": SITEMAP_NOINDEX_EXPECTED} if listed else {}),
                 "reproduce": [f"{_curl(u, cfg.user_agent)} | grep -i -E 'robots|nosnippet'" for u in urls[:3]]},
                "no directive that withholds the page from AI answers, unless intended",
                UTILITY_NOINDEX_FIX if utility else LISTED_NOINDEX_FIX if listed else
                "If these pages should appear in AI answers, remove the directive. If it is deliberate, mark it as "
                "intended for these pages (Info from then on).",
                intent=intent, launch_gated=g["gated"], importance_tier=_tier(urls, key_urls),
                notes=(["Google documents that AI Overviews/AI Mode require a page to be indexed and eligible for a "
                        "snippet; there is no control that removes content from AI features while keeping the normal "
                        "snippet."] if GOOGLE in g["engines"] else []),
            )

        # A utility page's noindex, and one the sitemap lists, is marked as intended like any noindex (DECISIONS 222).
        findings += _with_intent("ACC-3", "noindex" if condition in ("noindex_utility", "noindex_listed") else condition,
                                 items, g["severity"], key_urls, cfg, build)

    # A robots tag after the body started is not read as the page's (DECISIONS 167), so it never withholds a page
    # here. It is said once, as a note: what a real crawler does with such a tag is not established (LG-60).
    stray = {p.url: sorted({name for name in (p.analysis.get("outside_head") or {}).get("meta") or [] if name in META_NAMES})
             for p in pages}
    stray = {url: names for url, names in stray.items() if names}
    if stray:
        urls = list(stray)
        findings.append(Finding(
            "ACC-3", f"{len(urls)} page(s) carry a robots tag outside <head>: browsers ignore it; some crawlers may not",
            Severity.INFO, Confidence.VERIFIED, Rationale.HYPOTHESIS.value, ["crawlers that read a robots tag anywhere in the HTML"],
            scope_for(urls), {"robots_tags_outside_head": {u: stray[u] for u in urls[:40]}},
            "robots meta tags sit in the page's <head>, where every crawler reads them the same way",
            "Move the tag into <head> if it is meant, or remove it from the body if it is not (a widget or an embedded "
            "snippet often brings one along).",
            importance_tier=_tier(urls, key_urls),
            notes=["Verified: the tag is in the HTML after the body starts. Not established: which crawlers act on a robots "
                   "tag there. This audit does not treat the page as noindex because of it."]))

    findings += utility_indexable_findings(pages, key_urls, cfg.user_agent)

    evidence = {"pages_checked": len(pages), "non_html_documents_checked": len(documents),
                "non_html_documents": [{"url": d.url, "content_type": d.content_type,
                                        "x_robots_tag": d.headers.get("x-robots-tag")} for d in documents[:40]],
                "thresholds": {"min_max_snippet": cfg.min_max_snippet,
                                                            "data_nosnippet_share": cfg.data_nosnippet_share}}
    summary = (f"{len(findings)} finding(s) across {len(pages)} readable page(s) and {len(documents)} non-HTML "
               "document(s)." if findings else f"No AI-withholding directives on {len(pages)} readable page(s) or "
               f"{len(documents)} non-HTML document(s) (X-Robots-Tag).")
    if not pages:
        return CheckResult("ACC-3", title, "not_assessed", "No readable HTML pages to check.", evidence=evidence)
    return CheckResult("ACC-3", title, _status(findings), summary, findings, evidence)


# -- ACC-4 -------------------------------------------------------------------

ACC4_SEVERITY = {
    "search": {"blocked": Severity.S1, "challenged": Severity.S1, "rate_limited": Severity.S1, "degraded": Severity.S2},
    "live": {"blocked": Severity.S2, "challenged": Severity.S2, "rate_limited": Severity.S2, "degraded": Severity.S2},
}
# "different_content" and "redirected" have no severity: harm cannot be shown, but a bot being served something
# other than what a visitor sees, or sent somewhere else, always deserves a person's attention. They become
# visible review items.
REVIEW_OUTCOMES = ("different_content", "redirected")


def _response_row(r: dict) -> dict:
    """One response as evidence: what came back, measured the same way for the browser and the bot."""
    keys = ("requested_at", "user_agent", "status", "fetch_class", "location", "content_type", "body_bytes",
            "visible_words", "text_sha256", "title", "headers")
    return {**{k: r.get(k) for k in keys}, "evidence": r.get("classification_evidence", [])}


def acc4_ua_differential(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "User-agent differential response test"
    access = _access(result)
    key_urls = set(key_page_urls(result, cfg))
    if access.probes is None and getattr(access, "ua_check", None):
        return acc4_ua_check(result, cfg, access, key_urls)
    if access.probes is None:
        return CheckResult(
            "ACC-4", title, "not_assessed",
            f"{FIREWALL_NOT_ASSESSED} Reason: {access.probes_skipped_reason}. robots.txt rules (ACC-2) were checked, "
            "but they cannot show WAF or edge blocks.",
            evidence={"ownership": access.ownership, "reason": access.probes_skipped_reason},
        )

    probes = access.probes
    assessed = [s for s in probes["sample"] if s["assessed"]]
    unassessed = [s for s in probes["sample"] if not s["assessed"]]
    pairs = probes["pairs"]
    evidence = {
        "ownership": access.ownership,
        "browser_user_agent": probes["browser_user_agent"],
        "probe_headers": probes["probe_headers"],
        "bots_probed": probes["bots"],
        "urls_assessed": [s["url"] for s in assessed],
        "urls_not_assessed": [{"url": s["url"], "reason": s["reason"], "baseline_status": s["baseline"]["status"]}
                              for s in unassessed],
        "requests_used": probes["requests_used"], "cap": probes["cap"], "capped": probes["capped"],
        "caveat": ACC4_CAVEAT,
    }
    if not assessed:
        return CheckResult("ACC-4", title, "not_assessed",
                           "The browser baseline itself was blocked on every sampled URL, so blocking of AI bots "
                           "cannot be separated from blocking of datacenter traffic.", evidence=evidence)

    baselines = {s["url"]: s["baseline"] for s in assessed}
    # A pair is confirmed only when every configured retry also differed from the browser. The probe cap can
    # cut retries short; a difference seen once and never retried may be transient (spec ACC-4 step 5), so it
    # is reported apart, Estimated, with the same severity (spec §2.2: an estimate is never discounted).
    grouped: dict[tuple[str, str, bool], list[dict]] = defaultdict(list)
    for p in pairs:
        if p["outcome"] != "same":
            confirmed = True if p["outcome"] in REVIEW_OUTCOMES else bool(p["confirmed"])
            grouped[(p["outcome"], p["role"], confirmed)].append(p)

    findings: list[Finding] = []
    review_items: list[ReviewItem] = []
    for (outcome, role, confirmed), group_pairs in sorted(grouped.items()):
        by_key = {(p["url"], p["token"]): p for p in group_pairs}

        def rows_for(chosen):
            rows = []
            for p in chosen[:40]:
                base = baselines[p["url"]]
                rows.append({
                    "url": p["url"], "token": p["token"], "outcome": p["outcome"], "confirmed": p["confirmed"],
                    "browser": _response_row(base),
                    "notes": p["notes"],
                    "attempts": [_response_row(a) for a in p["attempts"]],
                    "browser_rebaselines": [_response_row(r) for r in p.get("browser_rebaselines", [])],
                    "text_delta": p.get("text_delta"),
                    "reproduce_browser": _curl(p["url"], probes["browser_user_agent"], probe=True),
                    "reproduce_bot": _curl(p["url"], entry(p["token"]).probe_user_agent, probe=True),
                })
            return rows

        if outcome in REVIEW_OUTCOMES:
            tokens = sorted({p["token"] for p in group_pairs})
            urls = sorted({p["url"] for p in group_pairs})
            what = ("were redirected somewhere a browser was not sent" if outcome == "redirected"
                    else "received different content than a browser")
            review_items.append(ReviewItem(
                "ACC-4", f"Requests with {role} bot user agents {what} on {len(urls)} URL(s): {', '.join(tokens)}",
                ("A bot was redirected where a visitor is not. Where it lands may be a login or block page, or a "
                 "harmless locale redirect; the Location is in the evidence." if outcome == "redirected" else
                 "A bot was served something other than what a visitor sees (a different status, content type, "
                 "title, or visible text; the text delta is in the evidence). Harm is not established, so there "
                 "is no severity, but a person should look: it may be cloaking, a bot-specific page, or harmless "
                 "personalization."),
                Confidence.VERIFIED, sorted({entry(t).engine for t in tokens}), scope_for(urls),
                {"pairs": rows_for(group_pairs), "caveat": ACC4_CAVEAT},
                "Compare the browser and bot responses with the reproduce commands. If the difference is intended, no "
                "action is needed; if not, make both user agents receive the same page.",
                launch_gated=_gates(tokens, probes=True), importance_tier=_tier(urls, key_urls),
            ))
            continue

        def build(its, severity, intent, outcome=outcome, role=role, by_key=by_key, confirmed=confirmed):
            chosen = [by_key[i] for i in its]
            tokens = sorted({p["token"] for p in chosen})
            urls = sorted({p["url"] for p in chosen})
            rows = rows_for(chosen)
            # Per-pair details (statuses, word counts) stay in the pair rows; only site-level notes are lifted.
            notes = {n for p in chosen for n in p["notes"] if "X-Powered-By" in n or "transport failure" in n}
            unconfirmed_note = [] if confirmed else [
                "Not confirmed: the probe cap was reached before this difference could be retried "
                f"({cfg.probe_retries} retries configured). The response itself is Verified; that it is a lasting "
                "block rather than a transient one is Estimated. Re-run with a larger probe cap "
                "(CrawlConfig.max_probe_requests) to confirm."]
            return Finding(
                "ACC-4", f"Requests with {role} bot user agents were {outcome.replace('_', ' ')} on {len(urls)} URL(s): "
                         f"{', '.join(tokens)}" + ("" if confirmed else " (seen once, not retried)"),
                severity, Confidence.VERIFIED if confirmed else Confidence.ESTIMATED,
                "Documented (vendors require access) + practitioner case study",
                sorted({entry(t).engine for t in tokens}), scope_for(urls),
                {"pairs": rows, "caveat": ACC4_CAVEAT, "confirmed_by_retries": confirmed,
                 "bot_provenance": {t: entry(t).provenance() for t in tokens},
                 "confidence_detail": ("Verified: Maya's own observation, repeated on every retry. Inferred: what "
                                       "the real bot receives.") if confirmed else
                                      ("Verified: one response Maya received. Estimated: that it persists (not "
                                       "retried). Inferred: what the real bot receives.")},
                "bots receive the same page a browser does",
                "Allow these user agents in your WAF, bot-protection, and rate-limiting rules (verify real bots by "
                "their published IP ranges rather than trusting the user-agent string). If blocking is deliberate, "
                "mark it as intended.",
                intent=intent, launch_gated=_gates(tokens, probes=True),
                notes=[ACC4_CAVEAT, *unconfirmed_note, *sorted(notes)],
                importance_tier=_tier(urls, key_urls),
            )

        severity = ACC4_SEVERITY[role][outcome]
        items = [(p["url"], p["token"]) for p in group_pairs]
        findings += _with_intent("ACC-4", outcome, items, severity, key_urls, cfg, build)

    transient = [{"url": p["url"], "token": p["token"], "first_outcome": p["first_outcome"]}
                 for p in pairs if p["outcome"] == "same" and p["first_outcome"] != "same"]
    observations = [{"metric": "transient difference, matched the browser on retry", **t} for t in transient]
    same = sum(p["outcome"] == "same" for p in pairs)
    if findings or review_items:
        summary = (f"{len(findings)} finding(s) and {len(review_items)} item(s) needing review from {len(pairs)} "
                   f"bot/URL pairs; {same} matched the browser.")
    else:
        summary = f"All {len(pairs)} bot/URL pairs matched the browser response."
    if unassessed:
        summary += f" {len(unassessed)} URL(s) not assessed (browser baseline blocked)."
    return CheckResult("ACC-4", title, _status(findings, review_items), summary, findings, evidence, observations,
                       review_items)


def acc4_ua_check(result: CrawlResult, cfg: CrawlConfig, access: AccessData, key_urls: set[str]) -> CheckResult:
    """ACC-4 without ownership (DECISIONS 205): what a browser and Googlebot's user agent were each answered, once.

    Googlebot 5xx where the browser got 2xx is S2; 403, 429 or a challenge is S3; the same status with a body under
    half or over twice the browser's is Info. All Estimated: the request was not Google's, and was not retried."""
    title = "User-agent differential response test"
    check = access.ua_check
    pairs = check["pairs"]
    assessed = [p for p in pairs if p["assessed"]]
    unassessed = [p for p in pairs if not p["assessed"]]
    evidence = {
        "ownership": access.ownership, "reason": access.probes_skipped_reason, "mode": "ua_check",
        "browser_user_agent": check["browser_user_agent"], "bot_user_agent": check["bot_user_agent"],
        "probe_headers": check["probe_headers"], "bots_probed": [check["bot"]],
        "urls_assessed": [p["url"] for p in assessed],
        "urls_not_assessed": [{"url": p["url"], "reason": p["reason"],
                               "baseline_status": (p.get("browser") or {}).get("status")} for p in unassessed],
        "requests_used": check["requests_used"], "cap": check["cap"], "retries": 0,
        "caveat": UA_CHECK_NOTE,
        "pairs": [{"url": p["url"], "outcome": p.get("outcome"), "notes": p.get("notes", []),
                   "browser": _response_row(p["browser"]) if p.get("browser") else None,
                   "googlebot": _response_row(p["googlebot"]) if p.get("googlebot") else None} for p in pairs],
    }
    summary = UA_CHECK_SUMMARY.format(n=len(assessed))
    if not assessed:  # nothing could be compared: said as before, with what was tried in the evidence
        return CheckResult(
            "ACC-4", title, "not_assessed",
            f"{FIREWALL_NOT_ASSESSED} Reason: {access.probes_skipped_reason}. robots.txt rules (ACC-2) were checked, "
            "but they cannot show WAF or edge blocks.", evidence=evidence)
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for p in assessed:
        if p["outcome"] in UA_CHECK_SEVERITY:
            key = ((p["outcome"], p["googlebot"]["status"], p["browser"]["status"])
                   if p["outcome"] not in ("size", "empty_for_bot", "challenged") else (p["outcome"], None, None))
            grouped[key].append(p)
    findings: list[Finding] = []
    m = len(assessed)
    for (outcome, status, browser), group in sorted(grouped.items(), key=lambda kv: (UA_CHECK_SEVERITY[kv[0][0]].value, str(kv[0]))):
        urls = [p["url"] for p in group]
        if outcome == "size":
            what = f"{len(urls)} of {m} URL(s) sent Googlebot's user agent a page of very different size than a browser's"
        elif outcome == "empty_for_bot":
            what = f"{len(urls)} of {m} URL(s) sent Googlebot's user agent an empty page where a browser got the page"
        elif outcome == "challenged":
            what = (f"{len(urls)} of {m} URL(s) challenged Googlebot's user agent from Maya's address: the real Googlebot "
                    "may be on a verified-bot allowlist")
        else:
            what = (f"A request with Googlebot's user agent got {status} on "
                    f"{len(urls)} of {m} URL(s) where a browser got {browser}")
        rows = [{"url": p["url"], "outcome": p["outcome"], "notes": p["notes"],
                 "browser": _response_row(p["browser"]), "googlebot": _response_row(p["googlebot"]),
                 "reproduce_browser": _curl(p["url"], check["browser_user_agent"], probe=True),
                 "reproduce_bot": _curl(p["url"], check["bot_user_agent"], probe=True)} for p in group]
        findings.append(Finding(
            "ACC-4", what, UA_CHECK_SEVERITY[outcome], Confidence.ESTIMATED,
            "Documented (vendors require access) + practitioner case study", [GOOGLE], scope_for(urls),
            {"pairs": rows, "caveat": UA_CHECK_NOTE, "mode": "ua_check", "confirmed_by_retries": False,
             "size_rule": "same status, body under half or over twice the browser's" if outcome == "size" else None,
             "confidence_detail": "Verified: one response Maya received. Estimated: that it persists (not retried), and "
                                  "that Google's own crawler is answered the same way."},
            "Googlebot receives the same page a browser does",
            (REFUSED_FIX if outcome == "refused" else
             "Allow Googlebot in your WAF, bot-protection, and rate-limiting rules (verify it by Google's published IP "
             "ranges rather than trusting the user-agent string). If blocking is deliberate, mark it as intended."),
            notes=[UA_CHECK_NOTE], importance_tier=_tier(urls, key_urls)))
    # Never a pass: the other AI crawlers were not tested (maya_audit.coverage turns a clean result into "partial").
    return CheckResult("ACC-4", title, _status(findings), summary, findings, evidence)


# -- ACC-5 -------------------------------------------------------------------

def acc5_log_traffic(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Real AI-bot traffic from access logs"
    access = _access(result)
    logs = access.logs
    if logs is None:
        return CheckResult("ACC-5", title, "not_assessed",
                           "Requires server or CDN access logs (cost tier T3); none were provided.")
    policy = result.robots_policy_by_origin[result.origin]
    observations = []
    for token, stats in sorted(logs["bots"].items()):
        e = entry(token)
        if stats["verified"]:
            non_2xx = sum(n for code, n in stats["verified_status"].items() if not 200 <= code < 300)
            observations.append({
                "bot": token, "role": e.role, "metric": "non-2xx share of IP-verified requests",
                "value": f"{non_2xx}/{stats['verified']} ({100 * non_2xx / stats['verified']:.1f}%)",
                "status_split": stats["verified_status"],
                "threshold": "not set (spec follow-up: '≥X% non-2xx')",
            })
            observations.append({
                "bot": token, "role": e.role, "metric": "last seen (IP-verified)", "value": stats["last_seen_verified"],
                "threshold": "not set (spec follow-up: 'not seen in N days')",
            })
        if stats["spoofed"]:
            observations.append({"bot": token, "metric": "requests claiming this bot from IPs outside its published ranges",
                                 "value": stats["spoofed"], "ip_sample": stats["spoofed_ip_sample"]})
        if stats["unverifiable"]:
            observations.append({"bot": token, "metric": "requests that could not be IP-verified (no range file loaded)",
                                 "value": stats["unverifiable"]})

    # Only a file that gave at least one network verifies anything (D-15).
    loaded = {r["token"] for r in logs["ip_range_files"] if r.get("prefixes", 1)}
    search_with_ranges = [e for e in by_role("search") if e.token in loaded]
    evidence = {"files": logs["files"], "format": logs["format"], "entries_parsed": logs["entries_parsed"],
                "lines_unparsed": logs["lines_unparsed"], "window": logs["window"],
                "ip_range_files": logs["ip_range_files"]}
    findings: list[Finding] = []
    if not search_with_ranges:
        evidence["never_fetched_check"] = "not assessed: no IP ranges loaded for any search bot"
    else:
        fetched_paths = set()
        for e in search_with_ranges:
            fetched_paths |= logs["bots"].get(e.token, {}).get("verified_paths", set())
        readable = [p.url for p in result.pages
                    if p.fetch_class == FetchClass.OK and p.status and 200 <= p.status < 300 and is_html(p.content_type)]
        never = [u for u in readable
                 if any(policy.decide(e.token, u).allowed for e in search_with_ranges)
                 and request_target(u) not in fetched_paths]
        if never:
            templates = detect_templates(never)
            key_urls = set(key_page_urls(result, cfg))
            findings.append(Finding(
                "ACC-5", f"{len(never)} crawled page(s) that search bots may fetch were not fetched by any IP-verified "
                         "search bot in the log window",
                Severity.S4, Confidence.VERIFIED, Rationale.DOCUMENTED.value,
                sorted({e.engine for e in search_with_ranges}), scope_for(never),
                {"by_template": {t: len(us) for t, us in sorted(templates.items())}, "window": logs["window"],
                 "search_bots_with_ip_ranges": [e.token for e in search_with_ranges]},
                "pages you want cited are visited by search bots",
                "Absence in the log window is an observation, not proof of blocking. Check internal links and sitemaps "
                "for these pages, and re-check with a longer log window.",
                cost_tier="T3", notes=[f"Only IP-verified requests count; window {logs['window']['start']} to "
                                       f"{logs['window']['end']}."],
                importance_tier=_tier(never, key_urls),
            ))
    summary = (f"{logs['entries_parsed']} log entries; {len(observations)} measured value(s) awaiting thresholds; "
               f"{len(findings)} finding(s).")
    for f in findings:
        f.cost_tier = "T3"
    return CheckResult("ACC-5", title, _status(findings), summary, findings, evidence, observations)


# -- ACC-6 -------------------------------------------------------------------

VENDOR_NOTES = {
    "Google": "Blocking Google-Extended does not remove the site from AI Overviews or AI Mode, which use Googlebot and "
              "the Search index.",
    "OpenAI": "Blocking GPTBot does not block OAI-SearchBot (ChatGPT search) or ChatGPT-User.",
    "Anthropic": "Blocking ClaudeBot does not block Claude-SearchBot or Claude-User.",
    "Apple": "Applebot-Extended only opts out of training; Applebot (search) is a separate token.",
    "Common Crawl": "Common Crawl's corpus is used by many model trainers; it does not affect live AI search.",
}


def acc6_training_scope(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Training vs search token scope"
    access = _access(result)
    policy = result.robots_policy_by_origin[result.origin]
    if policy.stops_requests:
        return CheckResult("ACC-6", title, "not_assessed", f"Not checked: {policy.reason}." if policy.mode == "not_checked"
                           else "robots.txt unavailable; see ACC-1.")
    sample = [s["url"] for s in access.url_sample]

    def status(token):
        if token is None:
            return None, "no token"
        blocked = sum(not policy.decide(token, u).allowed for u in sample)
        if blocked == 0:
            return blocked, "allowed"
        return blocked, "blocked" if blocked == len(sample) else f"partly blocked ({blocked}/{len(sample)} sampled URLs)"

    lines, findings = [], []
    for vendor, training, search, live in VENDOR_SCOPES:
        (tb, ts), (sb, ss), (_lb, ls) = status(training), status(search), status(live)
        line = f"{vendor}: Training{f' ({training})' if training else ''}: {ts} · Search{f' ({search})' if search else ''}: {ss} · Live fetch{f' ({live})' if live else ''}: {ls}"
        lines.append(line)
        if training and tb:
            notes = [VENDOR_NOTES[vendor]] if vendor in VENDOR_NOTES else []
            if search and sb and cfg.policy.search_bots != "block":
                notes.append(f"{search} is also blocked. That is reported once, as an ACC-2 finding, not repeated here.")
            intent = ({"kind": "declared_policy", "policy": "training_bots=block", "severity_otherwise": Severity.INFO.value}
                      if cfg.policy.training_bots == "block" else None)
            findings.append(Finding(
                "ACC-6", line, Severity.INFO, Confidence.INFERRED, Rationale.DOCUMENTED.value,
                [e.engine for e in REGISTRY if e.vendor == vendor], scope_for(sample, sitewide=True),
                {"training_token": training, "search_token": search, "live_token": live, "sample_size": len(sample),
                 "blocked_tokens": [t for t, n in ((training, tb), (search, sb), (live, _lb)) if t and n]},
                "training and search access set independently, as intended",
                "No action needed if this matches your policy. Each token is controlled separately in robots.txt.",
                intent=intent, launch_gated=_gates([t for t in (training, search, live) if t]), notes=notes,
            ))
    summary = " | ".join(lines)
    return CheckResult("ACC-6", title, "findings" if findings else "pass", summary, findings, {"vendor_lines": lines})


# -- ACC-7 -------------------------------------------------------------------

def acc7_crawl_delay(result: CrawlResult, cfg: CrawlConfig, acc4: CheckResult | None = None) -> CheckResult:
    title = "Crawl-delay and rate-limit posture toward AI bots"
    policy = result.robots_policy_by_origin[result.origin]
    robots_url = f"{result.origin}/robots.txt"
    key_urls = set(key_page_urls(result, cfg))
    findings: list[Finding] = []
    values = []
    if policy.robots is not None:
        for group in policy.robots.groups:
            if not group.crawl_delay:
                continue
            seconds, line = group.crawl_delay
            ai_tokens = [e.token for e in REGISTRY if any(g is group for g in select_groups(policy.robots, e.token)[0])]
            applies_to_maya = any(g is group for g in select_groups(policy.robots, cfg.product_token)[0])
            values.append({"line": line, "seconds": seconds, "user_agent_lines": [n for _, n in group.agents],
                           "applies_to": ai_tokens + ([cfg.product_token] if applies_to_maya else [])})

            if ai_tokens and seconds >= cfg.high_crawl_delay_s:
                def build(its, severity, intent, seconds=seconds, line=line):
                    tokens = sorted({t for _, t in its})
                    return Finding(
                        "ACC-7", f"Crawl-delay: {seconds:g}s (robots.txt line {line}) applies to {', '.join(tokens)}",
                        severity, Confidence.VERIFIED, "Documented (directive) / Hypothesis (magnitude)",
                        sorted({entry(t).engine for t in tokens}), scope_for([robots_url], sitewide=True),
                        {"robots_url": robots_url, "line": line, "seconds": seconds,
                         "max_fetches_per_day_estimate": int(86400 // seconds),
                         "reproduce": f"curl -s {shlex.quote(robots_url)} | sed -n '{line}p'"},
                        f"Crawl-delay below {cfg.high_crawl_delay_s:g}s for bots you want refreshing your pages",
                        "Lower or remove the Crawl-delay for these bots if you want pages refreshed quickly. If this is "
                        "deliberate, mark it as intended.",
                        intent=intent, launch_gated=_gates(tokens),
                        notes=[f"Estimated effect: at most about {int(86400 // seconds)} fetches per day per bot, "
                               "assuming the bot honors Crawl-delay (it is non-standard; not all do)."],
                    )
                items = [(robots_url, t) for t in ai_tokens]
                findings += _with_intent("ACC-7", "crawl-delay", items, Severity.S4, key_urls, cfg, build)

            if applies_to_maya and seconds > cfg.max_crawl_delay_s:
                findings.append(Finding(
                    "ACC-7", f"robots.txt asks {cfg.product_token} to wait {seconds:g}s between requests (line {line}); "
                             f"Maya honored {cfg.max_crawl_delay_s:g}s, its cap",
                    Severity.INFO, Confidence.VERIFIED, Rationale.DOCUMENTED.value, [f"{cfg.product_token} (this audit)"],
                    scope_for([robots_url], sitewide=True),
                    {"declared_seconds": seconds, "honored_seconds": cfg.max_crawl_delay_s, "line": line},
                    "Crawl-delay honored as declared",
                    "No action needed. Maya caps Crawl-delay so an audit can finish; the declared value is reported here.",
                ))

    evidence = {"crawl_delays": values, "high_crawl_delay_threshold_s": cfg.high_crawl_delay_s}
    if acc4 is not None:
        rate_limited = [f.id for f in acc4.findings if "rate limited" in f.title]
        evidence["rate_limit_findings_in_acc4"] = rate_limited or "none"
        evidence["rate_limit_note"] = "429 responses to bot user agents are reported once, in ACC-4."
    logs = _access(result).logs
    observations = []
    if logs:
        for token, stats in logs["bots"].items():
            if stats["verified_status"].get(429):
                observations.append({"bot": token, "metric": "IP-verified requests answered 429",
                                     "value": stats["verified_status"][429]})
    summary = (f"{len(findings)} finding(s)." if findings
               else f"No Crawl-delay of {cfg.high_crawl_delay_s:g}s or more applies to AI bots.")
    return CheckResult("ACC-7", title, _status(findings), summary, findings, evidence, observations)


# -- ACC-8 -------------------------------------------------------------------

# Said after the links' title when some of them lead to IDX-1's empty pages (maya_audit.root_cause, DECISIONS 215).
IDX1_SUFFIX = "; {same} of them lead to the empty pages reported under IDX-1"


def acc8_llms_txt(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "llms.txt presence (recorded, not scored)"
    docs = _access(result).llms
    # A 200 that is an HTML page (a soft 404) is not the file (B15); a report saved before `readable` keeps its reading.
    present = [d for d in docs if d.get("status") == 200 and d.get("readable", True)]
    findings = [
        Finding(
            "ACC-8", f"{d['url'].rsplit('/', 1)[-1]} is present", Severity.INFO, Confidence.VERIFIED,
            Rationale.HYPOTHESIS.value, ["none documented"], scope_for([d["url"]], sitewide=True),
            {**d, "markdown_check": "Estimated (opens with a Markdown H1)", "reproduce": _curl(d["url"], cfg.user_agent)},
            "nothing required", "No action needed.",
            notes=["No major answer engine documents consuming llms.txt, and Google says AI features need no special "
                   "text files. Recorded only; never a warning when absent."],
        )
        for d in present
    ]
    summary = (", ".join(f.title for f in findings) if findings
               else "No llms.txt or llms-full.txt (not a problem: no major answer engine documents using them).")
    from ..access_data import LLMS_BAD_KINDS

    for d in present:
        name = d["url"].rsplit("/", 1)[-1]
        links = d.get("links") or {}
        bad = [r for r in links.get("rows") or [] if r.get("works") is False]
        if links.get("not_working") and bad:
            kinds = ", ".join(LLMS_BAD_KINDS[k] for k in LLMS_BAD_KINDS if (links.get("kinds") or {}).get(k))
            findings.append(Finding(
                "ACC-8", f"{links['not_working']} of {links['checked']} link(s) in {name} lead to pages that do not work ({kinds})",
                Severity.S4, Confidence.VERIFIED, Rationale.HYPOTHESIS.value, ["AI tools that read llms.txt"],
                scope_for([d["url"]], sitewide=True),
                {"file": d["url"], "links": {k: v for k, v in links.items() if k != "rows"}, "not_working": bad[:40],
                 "judged_from": "the crawl, the sitemap check, or one light request each (at most 64 KB read, no redirect followed); "
                                "a link to another site with one HEAD request, where only 404 or 410 counts and a redirect works"},
                "every link in llms.txt leads to a live page",
                "Regenerate the file from live pages only, or fix the pages it lists."))
        moved = links.get("redirecting") or []
        if moved:  # each link should name the page itself, not an address that sends the reader on (B15)
            findings.append(Finding(
                "ACC-8", f"{len(moved)} link(s) in {name} point to an address that redirects", Severity.INFO, Confidence.VERIFIED,
                Rationale.HYPOTHESIS.value, ["AI tools that read llms.txt"], scope_for([d["url"]], sitewide=True),
                {"file": d["url"], "redirecting": moved}, "every link in llms.txt names the page's final address",
                "Replace each listed address with the address it redirects to."))
        line = d.get("first_line")
        if line is not None and not line.startswith("# "):
            findings.append(Finding(
                "ACC-8", f"{name} does not open with a “# ” title line", Severity.INFO, Confidence.VERIFIED,
                Rationale.HYPOTHESIS.value, ["AI tools that read llms.txt"], scope_for([d["url"]], sitewide=True),
                {"file": d["url"], "first_line": line}, "llms.txt opens with one “# Site name” line",
                "Start the file with one line “# Site name”, as the llms.txt proposal describes.",
                notes=[f"First line: “{line[:120]}”."]))
    return CheckResult("ACC-8", title, "findings" if findings else "pass", summary, findings, {"documents": docs})


# -- ACC-9 ---------------------------------------------------------------------

def blocker_phrase(blockers: list[dict]) -> str:
    """"Cloudflare (bot challenge)" for the commonest blocker; a plain description when nothing names itself."""
    if not blockers:
        return "the site or its firewall"
    top = blockers[0]
    return f"{top['name']} ({top['kind']})" if top["name"] else {
        "rate limit": "the site's rate limiting (HTTP 429)", "bot challenge": "a bot challenge",
    }.get(top["kind"], f"the site or its firewall (HTTP {top['status']}, access denied)")


FIX_429 = ('Check the bot and rate-limit rules in {who} that answer page requests with 429 while robots.txt and the sitemap are served: allow the user agent "{token}" and run the audit again. AI crawlers may get the same treatment: check the same rules for OAI-SearchBot, ClaudeBot, PerplexityBot and the others you want to reach you.')


# DECISIONS 289: some pages answered 429 (not all, or the site's files were refused too): rate-limited, said as that.
FIX_RATE_429 = ('Check the bot and rate-limit rules in {who} that answer page requests with 429: allow the user agent "{token}" and run the audit again. AI crawlers may get the same treatment: check the same rules for OAI-SearchBot, ClaudeBot, PerplexityBot and the others you want to reach you.')


def acc9_automated_visitors(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    """What the site did to an automated visitor that says who it is: Maya's own crawler.

    Measured: Maya's requests were answered with a block, a challenge or a rate limit. Not measured: what an AI
    crawler receives. A rule that stops one unknown bot often stops others, so the finding says they may be
    affected; ACC-4 (ownership verified) is the check that tests their user agents. Nothing here retries with a
    different identity or tries to get past the protection.
    """
    from ..classify import describe_blockers, identify_blocker
    from ..models import FetchClass

    title = "Automated visitors blocked or challenged"
    pages = [p for p in result.pages if not (p.status is not None and 300 <= p.status < 400)]
    if not pages:
        return CheckResult("ACC-9", title, "not_assessed", "No page was requested, so there is nothing to report.")
    impaired = [p for p in pages if p.fetch_class in (FetchClass.BLOCKED, FetchClass.RATE_LIMITED)]
    start = next((p for p in result.pages if p.url == homepage_url(result)), None)
    # robots.txt and the sitemap answered the same way: the protection sits in front of the whole site.
    support = sorted({r.url for r in result.requests if r.purpose in ("robots", "robots_sample", "sitemap")
                      and r.status in (401, 403, 429)})
    if not impaired:
        return CheckResult("ACC-9", title, "pass", f"None of the {len(pages)} page(s) requested answered Maya's crawler with a "
                           "block, a challenge or a rate limit.", evidence={"pages_requested": len(pages), "user_agent": result.user_agent})
    blockers = describe_blockers([b for b in (identify_blocker(p.status, p.headers, p.classification_evidence, p.fetch_class.value)
                                              for p in impaired) if b])
    who = blocker_phrase(blockers)
    read = len(pages) - len(impaired)
    urls = [p.url for p in impaired]
    start_hit = start is not None and start in impaired
    widespread = start_hit or len(impaired) / len(pages) >= cfg.degraded_threshold
    from .. import maya_blocked
    blocked_429 = maya_blocked.holds(result)  # DECISIONS 288: 429 on every page while the site's files are served
    name = (blockers[0]["name"] if blockers and blockers[0].get("name") else "the site's firewall")
    rate_429 = not blocked_429 and bool(blockers) and blockers[0].get("kind") == "rate limit"
    rest = (Severity.S3 if widespread else Severity.S4, Confidence.INFERRED,
            "Measured (Maya's own requests) / Hypothesis (what AI crawlers receive)",
            ["all crawlers that identify themselves", "AI search and live-fetch bots"],
            scope_for(urls, sitewide=start_hit and read == 0),
            {"blocked_by": blockers, "pages_requested": len(pages), "pages_read": read, "pages_blocked_or_challenged": len(impaired),
             "start_url_blocked": start_hit, "robots_or_sitemap_also_refused": support[:10], "user_agent": result.user_agent,
             "maya_blocked": maya_blocked.LABEL if blocked_429 else None,
             "pages": [{"url": p.url, "status": p.status, "why": p.classification_evidence} for p in impaired[:40]],
             "reproduce": f"curl -i -A {result.user_agent!r} {urls[0]}", "not_measured": "what any AI crawler receives (ACC-4 tests that, on verified sites)"})
    # Each title, fix and note is written out in its own call: the wording tests read them from this source.
    if blocked_429:
        finding = Finding("ACC-9", f"Maya's crawler blocked (429 on pages): {name} answered {len(impaired)} of {len(pages)} page request(s) with 429 "
                          "while robots.txt and the sitemap were served. AI crawlers may get the same treatment",
                          *rest, expected="a crawler that identifies itself honestly receives the page",
                          how_to_fix=FIX_429.format(who=name, token=cfg.product_token), importance_tier=0 if start_hit else 2,
                          notes=["Measured: Maya's crawler was blocked, challenged or rate-limited. Inferred: bot protection that stops one "
                                 "self-identified crawler often stops others, but AI crawlers were not tested here and may be allowed by name.",
                                 "This is common on banks, large retailers and sites behind a managed firewall, and is often not deliberate.",
                                 "Maya does not try to get past bot protection."])
    elif rate_429:
        finding = Finding("ACC-9", f"Maya's crawler rate-limited (429 on pages): {name} answered {len(impaired)} of {len(pages)} page request(s) "
                          "with 429. AI crawlers may get the same treatment",
                          *rest, expected="a crawler that identifies itself honestly receives the page",
                          how_to_fix=FIX_RATE_429.format(who=name, token=cfg.product_token), importance_tier=0 if start_hit else 2,
                          notes=["Measured: Maya's crawler was blocked, challenged or rate-limited. Inferred: bot protection that stops one "
                                 "self-identified crawler often stops others, but AI crawlers were not tested here and may be allowed by name.",
                                 "This is common on banks, large retailers and sites behind a managed firewall, and is often not deliberate.",
                                 "Maya does not try to get past bot protection."])
    else:
        finding = Finding("ACC-9", f"The site blocks or challenges automated visitors: {who} answered {len(impaired)} of {len(pages)} page "
                          "request(s). AI crawlers may be affected too",
                          *rest, expected="a crawler that identifies itself honestly receives the page",
                          how_to_fix=f'If you own this site: allow the user agent "{cfg.product_token}" in the firewall or bot-protection '
                          "rules and run the audit again; verify ownership so ACC-4 can test what AI crawlers receive; or try again "
                          "later if this was a rate limit. Then check the same rules for the AI crawlers you want to reach you "
                          "(OAI-SearchBot, ClaudeBot, PerplexityBot and others).", importance_tier=0 if start_hit else 2,
                          notes=["Measured: Maya's crawler was blocked, challenged or rate-limited. Inferred: bot protection that stops one "
                                 "self-identified crawler often stops others, but AI crawlers were not tested here and may be allowed by name.",
                                 "This is common on banks, large retailers and sites behind a managed firewall, and is often not deliberate.",
                                 "Maya does not try to get past bot protection."])
    summary = (f"1 finding: {name} blocked Maya's crawler (429 on pages) on {len(impaired)} of {len(pages)} page request(s); "
               f"Maya's crawler read {read} page(s)." if blocked_429 else
               f"1 finding: {name} rate-limited Maya's crawler (429 on pages) on {len(impaired)} of {len(pages)} page request(s); "
               f"Maya's crawler read {read} page(s)." if rate_429 else
               f"1 finding: {who} answered {len(impaired)} of {len(pages)} page request(s) to Maya's crawler; {read} page(s) "
               "were read.")
    return CheckResult("ACC-9", title, _status([finding]), summary, [finding], {"blocked_by": blockers, "pages_read": read})


def run_access_checks(result: CrawlResult, cfg: CrawlConfig) -> list[CheckResult]:
    acc4 = acc4_ua_differential(result, cfg)
    return settle_all([
        acc1_robots_availability(result, cfg),
        acc2_robots_rules(result, cfg),
        acc3_page_controls(result, cfg),
        acc4,
        acc5_log_traffic(result, cfg),
        acc6_training_scope(result, cfg),
        acc7_crawl_delay(result, cfg, acc4),
        acc8_llms_txt(result, cfg),
        acc9_automated_visitors(result, cfg),
    ], result)
