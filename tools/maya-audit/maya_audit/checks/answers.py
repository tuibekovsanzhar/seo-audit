"""ANS-1 to ANS-3: answer-engine observations (spec §5 ANS).

These are samples of engine behavior, not facts about the site, so they live in
their own panel and never change a site finding's severity or confidence. Results
are per engine; engines are never summed (Maya's citation data has no locale, §8 Q7).
"No data" and "zero citations" are kept apart, and every result shows the citation
data's freshness.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from ..access_data import key_page_urls
from ..ans_data import CitationData
from ..ans_domains import CLASSES, CitationDomains
from ..config import CrawlConfig
from ..coverage import settle_all
from ..directives import noindex_directives
from ..findings import SEVERITY_ORDER, CheckResult, Finding, Rationale, ReviewItem, Severity, scope_for
from ..index_data import link_header_canonicals
from ..models import Confidence, CrawlResult, FetchClass
from ..registry import REGISTRY, by_role
from ..structure_data import readable_html
from ..urls import normalize_url
from .access import _status, _tier
from .structure import parse_number, price_tokens

CITATION_NOTE = ("The site-side result is Verified; that an engine cited the URL is an Estimated observation from "
                 "sampled answers (engine, model, and citedAt are in the evidence).")
PANEL_NOTE = "Listed because a cited URL fails a site-side check, whatever that finding's severity in the site report."
# Severities used only when the crawl never covered the cited URL, so no site check reported it. They copy the
# site checks' own values (spec §6): IDX-1 5xx/transport S1, unreferenced 4xx Info; ACC-2 search bot S1, live S3,
# training S4; ACC-3 noindex S1; IDX-4 canonicalized away S2.
# IDX-4 separates a canonical pointing at the same content (Info) from one pointing at different
# content (S2) by comparing the two pages. ANS-1 has not fetched the target, so it cannot tell them
# apart and takes the lower value rather than assuming the worse case; the note says so. The first
# audit of a client site hit this on trailing-slash canonicals (/x cited, /x/ declared).
OWN_SEVERITY = {"server_error": Severity.S1, "transport_error": Severity.S1, "not_found": Severity.INFO,
                "redirects": Severity.INFO, "noindex": Severity.S1, "canonicalized_away": Severity.INFO,
                "robots_disallowed_search": Severity.S1, "robots_disallowed_live": Severity.S3,
                "robots_disallowed_training": Severity.S4}
UNCOMPARED_CANONICAL = ("ANS-1 did not compare the two pages, so it cannot tell a canonical pointing at the "
                        "same content (IDX-4: Info) from one pointing at different content (IDX-4: S2). It "
                        "takes the lower value; crawl the target to have IDX-4 judge it.")
FAILURE_ORDER = ["transport_error", "server_error", "robots_disallowed_search", "noindex", "not_found",
                 "redirect_target_broken", "canonical_target_broken", "canonicalized_to_different_content",
                 "canonicalized_away", "content_missing_from_raw_html", "wall", "bot_blocked_by_edge",
                 "robots_disallowed_live", "robots_disallowed_training", "redirects", "not_fetched"]
# Which site check reports each failure, so a panel entry copies the severity of the check that reports it
# and not of some unrelated finding that happens to name the same URL.
REPORTED_BY = {"transport_error": ("IDX-1",), "server_error": ("IDX-1",), "not_found": ("IDX-1",),
               "redirects": ("IDX-3",), "noindex": ("ACC-3", "IDX-4"), "canonicalized_away": ("IDX-4",),
               "robots_disallowed_search": ("ACC-2",), "robots_disallowed_live": ("ACC-2",),
               "robots_disallowed_training": ("ACC-2", "ACC-6"), "content_missing_from_raw_html": ("RND-1",),
               "wall": ("RND-5",), "bot_blocked_by_edge": ("ACC-4",), "not_fetched": (),
               "redirect_target_broken": (), "canonical_target_broken": (), "canonicalized_to_different_content": ()}
# Where a cited URL hands its citation on (redirect or canonical), judged at the page it lands on (ANS-1 v2).
# Severities copy the site checks' own rules (spec §6): IDX-1 decision 15 (a redirect into a 4xx is a referenced
# 4xx, S2; into a 5xx or transport failure, S1), ACC-3 noindex S1, IDX-4 broken canonical S2, IDX-4 canonical to
# different content S2.
HANDOFF_FAILURES = ("redirects", "canonicalized_away")
SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _by_engine(records: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        out[record["engine"]].append(record)
    return dict(out)


def _citation_rows(records: list[dict]) -> list[dict]:
    """Per-engine citation evidence, newest first. Never summed across engines (spec)."""
    rows = []
    for engine, items in sorted(_by_engine(records).items()):
        newest = sorted(items, key=lambda r: r.get("cited_at") or "", reverse=True)
        rows.append({"engine": engine, "citations": len(items),
                     "most_recent_cited_at": newest[0].get("cited_at"),
                     "models": sorted({r.get("model") or "unknown" for r in items}),
                     "sample": [{"cited_at": r.get("cited_at"), "model": r.get("model"), "prompt": r.get("prompt")}
                                for r in newest[:3]]})
    return rows


def _no_data(check_id: str, title: str, data: CitationData) -> CheckResult | None:
    if data.path is None:
        return CheckResult(check_id, title, "not_assessed",
                           "Not assessed: no citation data (--citations). This is 'no data', not 'zero citations'.",
                           evidence={"citation_data": "none supplied"})
    if not data.loaded:
        return CheckResult(check_id, title, "not_assessed",
                           f"Not assessed: the citation file could not be read ({data.error}).",
                           evidence={"citation_file": data.path, "error": data.error})
    return None


def _site_findings_by_url(site_checks: list[CheckResult]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for check in site_checks:
        for finding in check.findings:
            for url in finding.scope.get("urls", []):
                out[url].append({"check_id": finding.check_id, "title": finding.title,
                                 "severity": finding.severity, "confidence": finding.confidence.value,
                                 "finding_id": finding.id})
    return out


def _site_view(url: str, result: CrawlResult, cfg: CrawlConfig, data: CitationData) -> dict[str, Any]:
    """What the site side says about one cited URL: from the crawl when it was crawled, else from the ANS fetch."""
    page = next((p for p in result.pages if p.url == url), None)
    view: dict[str, Any] = {"url": url, "failures": []}
    if page is not None:
        view.update(source="crawl", status=page.status, error=page.error, fetch_class=page.fetch_class.value,
                    location=page.redirect_location, requested_at=page.requested_at,
                    analysis=page.analysis, headers=page.headers, readable=readable_html(page))
    else:
        fetched = data.extra_fetches.get(url)
        if not fetched or not fetched.get("fetched"):
            # Not a failure of the site: Maya did not look. It is listed in ANS-1's coverage, and a robots.txt
            # block found below still makes it a finding.
            view.update(source="not_fetched", reason=(fetched or {}).get("reason", "not fetched"),
                        status=None, fetch_class=None, analysis=None, headers={})
        else:
            view.update(source="ans_fetch", status=fetched["status"], error=fetched["error"],
                        fetch_class=fetched["fetch_class"], location=fetched["location"],
                        requested_at=fetched["requested_at"], analysis=fetched["analysis"],
                        headers=fetched["headers"], readable=bool(fetched["analysis"]))
    status = view["status"]
    if view.get("fetch_class") in (FetchClass.BLOCKED.value, FetchClass.RATE_LIMITED.value):
        # The site answered Maya with a block, a bot challenge, or a rate limit (INT-1). That says nothing
        # about whether the page exists; seen live, a Cloudflare challenge's 403 was read as 13 "broken" pages.
        view["blocked_for_maya"] = True
    elif view.get("fetch_class") == FetchClass.ERROR.value:
        view["failures"].append("transport_error")
    elif status and status >= 500:
        view["failures"].append("server_error")
    elif status and 400 <= status < 500:
        view["failures"].append("not_found")
    elif status and 300 <= status < 400:
        view["failures"].append("redirects")
    if view.get("analysis") and not view.get("blocked_for_maya"):
        if noindex_directives(view["analysis"], view["headers"]):
            view["failures"].append("noindex")
            view["noindex"] = noindex_directives(view["analysis"], view["headers"])
        canonical = ([u for u in (normalize_url(h, url) for h in view["analysis"].get("canonicals", [])) if u]
                     or link_header_canonicals((view.get("headers") or {}).get("link"), url))
        if canonical and canonical[0] != url:
            view["failures"].append("canonicalized_away")
            view["canonical"] = canonical[0]
    policy = result.robots_policy_by_origin.get(result.origin)
    blocked = {}
    if policy is not None:
        for bot in REGISTRY:
            decision = policy.decide(bot.token, url)
            if not decision.allowed:
                blocked[bot.token] = {"role": bot.role, "rule": decision.to_dict()}
        for role in ("search", "live", "training"):
            if any(b["role"] == role for b in blocked.values()):
                view["failures"].append(f"robots_disallowed_{role}")
    view["robots_blocked_bots"] = blocked
    return view


def _observation(url: str, result: CrawlResult, data: CitationData) -> dict | None:
    """What Maya saw at a URL, from the crawl or from an ANS fetch; None when it was never fetched."""
    page = next((p for p in result.pages if p.url == url), None)
    if page is not None:
        return {"url": url, "source": "crawl", "status": page.status, "error": page.error,
                "fetch_class": page.fetch_class.value, "location": page.redirect_location,
                "analysis": page.analysis, "headers": page.headers}
    fetched = data.extra_fetches.get(url)
    if fetched and fetched.get("fetched"):
        return {**fetched, "source": "ans_fetch"}
    return None


def resolve_handoff(url: str, lookup, same_similarity: float = 0.9, block_share: float = 0.8) -> dict:
    """Follow a cited URL's redirect or canonical to the page it lands on, and judge that page.

    `lookup(url)` returns what was observed at a URL (status, location, analysis, headers) or None. Pure, so
    the same function can be run on a saved report's observations. Outcomes:
      consolidated        lands on a live, indexable page (for a canonical: with the same visible text)
      broken_target       lands on an error, a transport failure, or a noindexed page
      different_content   the canonical target is live but its visible text differs
      unresolved          a hop was never fetched (cap, robots.txt) — not assessed, never assumed
    """
    from ..ans_data import _next_hop

    first = lookup(url)
    chain, current, kind = [url], first, None
    for _ in range(6):
        if current is None:
            return {"outcome": "unresolved", "kind": kind, "chain": chain,
                    "reason": f"{chain[-1]} was not fetched (cap or robots.txt)"}
        nxt = _next_hop(current, chain[-1])
        if nxt is None or nxt in chain:
            break
        kind = kind or ("redirect" if current.get("status") and 300 <= current["status"] < 400 else "canonical")
        chain.append(nxt)
        current = lookup(nxt)
    final = current
    row = {"kind": kind, "chain": chain, "final_url": chain[-1], "final_status": final.get("status"),
           "final_source": final.get("source")}
    status, error = final.get("status"), final.get("error") or final.get("fetch_class") == "error"
    noindex = noindex_directives(final.get("analysis"), final.get("headers") or {}) if final.get("analysis") else []
    if error or (status and status >= 500):
        return {**row, "outcome": "broken_target", "severity": Severity.S1 if kind == "redirect" else Severity.S2,
                "why": "the target fails (5xx or transport error)"}
    if status and status >= 400:
        return {**row, "outcome": "broken_target", "severity": Severity.S2, "why": f"the target returns {status}"}
    if noindex:
        return {**row, "outcome": "broken_target", "severity": Severity.S1 if kind == "redirect" else Severity.S2,
                "why": "the target is noindexed", "noindex": noindex}
    if not (status and 200 <= status < 300):
        return {**row, "outcome": "unresolved", "reason": f"the target answered {status}; nothing to judge"}
    if kind == "redirect":
        return {**row, "outcome": "consolidated", "confidence": "verified",
                "comparison": "redirect ends at a live, indexable page"}
    from ..analysis import compare_content

    verdict = compare_content((first or {}).get("analysis") or {}, final.get("analysis") or {}, block_share,
                              same_similarity)
    detail = {"comparison": verdict["basis"], "comparison_value": verdict["value"],
              "confidence": verdict["confidence"], "differing_blocks": verdict["differing_blocks"]}
    if verdict["same"] is None:
        return {**row, **detail, "outcome": "unresolved", "reason": "the two pages' visible text could not be compared"}
    if verdict["same"]:
        return {**row, **detail, "outcome": "consolidated"}
    return {**row, **detail, "outcome": "different_content", "severity": Severity.S2}


def _checks_applied(url: str, view: dict, result: CrawlResult) -> dict[str, str]:
    """Which site-side checks actually looked at this cited URL, so "healthy" never claims more than was checked."""
    render = getattr(result, "render", None)
    access = getattr(result, "access", None)
    rendered = bool(render and (render.pages.get(url) or {}).get("ok"))
    probed = bool(access and access.probes and any(p["url"] == url for p in access.probes.get("pairs", [])))
    readable = bool(view.get("analysis"))
    return {
        "http_status": "checked",
        "robots_txt_per_ai_bot": "checked (rules, not what a bot actually receives)",
        "noindex_and_canonical": "checked" if readable else "not checked: no readable HTML",
        "raw_html_content_gap": ("checked against a rendered view" if rendered else
                                 "raw-HTML heuristics only (not rendered)" if view.get("source") == "crawl" and readable
                                 else "not checked"),
        "edge_blocking_acc4": ("probed" if probed else "not checked: " + (
            (access.probes_skipped_reason or "not in the probe sample") if access and access.probes is None
            else "not in the probe sample")),
    }


def _rnd_failures(url: str, site_checks: list[CheckResult], view: dict) -> None:
    for check in site_checks:
        for finding in check.findings:
            if url not in finding.scope.get("urls", []):
                continue
            if finding.check_id == "RND-1" and finding.severity in (Severity.S2, Severity.S3):
                view["failures"].append("content_missing_from_raw_html")
            if finding.check_id == "RND-5":
                view["failures"].append("wall")
            if finding.check_id == "ACC-4" and finding.severity != Severity.INFO:
                view["failures"].append("bot_blocked_by_edge")


# -- ANS-1 ---------------------------------------------------------------------

def ans1_cited_url_health(result: CrawlResult, cfg: CrawlConfig, data: CitationData,
                          site_checks: list[CheckResult]) -> CheckResult:
    title = "Health of URLs AI engines cite"
    empty = _no_data("ANS-1", title, data)
    if empty:
        return empty
    key_urls = set(key_page_urls(result, cfg))
    site_findings = _site_findings_by_url(site_checks)
    by_url: dict[str, list[dict]] = defaultdict(list)
    for record in data.records:
        by_url[record["url"]].append(record)

    findings, healthy, unchecked, consolidated, unresolved = [], [], [], [], []
    edge_unchecked = 0
    lookup = lambda u: _observation(u, result, data)  # noqa: E731
    for url, records in by_url.items():
        view = _site_view(url, result, cfg, data)
        _rnd_failures(url, site_checks, view)
        view["failures"] = sorted(set(view["failures"]), key=lambda f: FAILURE_ORDER.index(f) if f in FAILURE_ORDER else 99)
        citations = _citation_rows(records)
        handoff = None
        if view["failures"] and set(view["failures"]) <= set(HANDOFF_FAILURES):
            # The URL only hands its citation on. Judge where it lands instead of calling the hand-off a failure.
            handoff = resolve_handoff(url, lookup, cfg.same_content_similarity, cfg.same_content_block_share)
            view["handoff"] = handoff
            if handoff["outcome"] == "consolidated":
                consolidated.append({"url": url, **handoff, "cited_by": citations})
                continue
            if handoff["outcome"] == "unresolved":
                unresolved.append({"url": url, **handoff, "cited_by": citations})
                continue
            view["failures"] = [{"redirect": "redirect_target_broken"}.get(handoff["kind"], "canonical_target_broken")
                                if handoff["outcome"] == "broken_target" else "canonicalized_to_different_content"]
        if not view["failures"] and (view["source"] == "not_fetched" or view.get("blocked_for_maya")):
            reason = (view.get("reason") if view["source"] == "not_fetched" else
                      f"the site answered Maya with {view.get('status') or 'no status'} ({view.get('fetch_class')}), "
                      "a block or bot challenge, so the page itself was never seen (INT-1)")
            unchecked.append({"url": url, "reason": reason, "cited_by": citations})
            continue
        applied = _checks_applied(url, view, result)
        edge_unchecked += applied["edge_blocking_acc4"] != "probed"
        if not view["failures"]:
            healthy.append({"url": url, "status": view.get("status"), "checked_by": view["source"],
                            "checks_applied": applied, "cited_by": citations})
            continue
        all_for_url = site_findings.get(url, [])
        reported_by = {c for failure in view["failures"] for c in REPORTED_BY.get(failure, ())}
        related = [f for f in all_for_url if f["check_id"] in reported_by]
        other = [f for f in all_for_url if f["check_id"] not in reported_by]
        severity = min((f["severity"] for f in related), key=lambda s: SEVERITY_ORDER[s], default=Severity.INFO)
        notes = [PANEL_NOTE, CITATION_NOTE]
        if handoff is not None:
            severity = handoff["severity"]
            notes.append(f"The cited URL hands its citation on ({handoff['kind']}: {' → '.join(handoff['chain'])}); "
                         f"{handoff.get('why') or handoff.get('comparison')}. Severity follows the site checks' own "
                         "rule for that case (IDX-1 decision 15, ACC-3, IDX-4).")
        elif related:
            notes.append("Severity copied unchanged from the site check that reports this failure: "
                         + "; ".join(f"{f['check_id']} {f['severity'].value}" for f in related))
        else:
            severity = min((OWN_SEVERITY[f] for f in view["failures"] if f in OWN_SEVERITY),
                           key=lambda s: SEVERITY_ORDER[s], default=Severity.INFO)
            notes.append(f"No site finding covers this failure (the URL was not part of the crawl, or the check "
                         f"does not sample it), so ANS-1 applied the site checks' own severity for "
                         f"'{view['failures'][0]}' (spec §6): {severity.value}.")
            if "canonicalized_away" in view["failures"]:
                notes.append(UNCOMPARED_CANONICAL)
        findings.append(Finding(
            "ANS-1", f"Cited URL fails a site check ({', '.join(view['failures'])}): {url}", severity,
            Confidence.ESTIMATED if handoff and handoff.get("confidence") == "estimated" else Confidence.VERIFIED,
            Rationale.DOCUMENTED.value + " (an inaccessible page cannot be retrieved)",
            sorted({r["engine"] for r in records}), scope_for([url]),
            {"site_view": {k: v for k, v in view.items() if k not in ("analysis", "headers")},
             "checks_applied": applied,
             "cited_by": citations, "site_findings": [{**f, "severity": f["severity"].value} for f in related],
             "other_site_findings_for_this_url": [{**f, "severity": f["severity"].value} for f in other],
             "citation_confidence": "estimated (sampled answers)", "citation_data": data.freshness()},
            "cited URLs stay reachable, indexable, and readable in raw HTML",
            "Fix the underlying site finding. Citations already earned point at this URL.",
            cost_tier="T4+T0", importance_tier=_tier([url], key_urls), notes=notes))

    # Panel order (spec): failure type, then most recent citedAt. Two stable sorts.
    findings.sort(key=lambda f: max((c["most_recent_cited_at"] or "") for c in f.evidence["cited_by"]), reverse=True)
    findings.sort(key=lambda f: FAILURE_ORDER.index(f.evidence["site_view"]["failures"][0])
                  if f.evidence["site_view"]["failures"][0] in FAILURE_ORDER else 99)
    per_engine = {row["engine"]: row["citations"] for row in _citation_rows(data.records)}
    evidence = {"citation_data": data.freshness(), "citation_file": data.path,
                "cited_urls_on_this_site": len(by_url), "citations_per_engine": per_engine,
                "engines": data.engines, "cross_engine_totals": "not shown (citation data has no locale, spec §8 Q7)",
                "healthy_cited_urls": healthy[:60], "cited_urls_not_on_this_site": data.off_site[:40],
                "invalid_records": data.invalid_records[:20],
                "sample_size": data.sample or "not supplied by the citation source",
                "cited_url_fetches": [v for v in data.extra_fetches.values() if not v.get("fetched")][:20],
                "cited_urls_not_checked": unchecked[:40],
                "consolidated_cited_urls": consolidated[:60],
                "cited_urls_with_unresolved_handoff": unresolved[:40],
                "edge_blocking_not_assessed_count": edge_unchecked,
                "input_completeness": _input_completeness(data)}
    if not data.records:
        if evidence["input_completeness"].startswith("incomplete"):
            # A paged or partly invalid export can omit this site's citations: that is "no data", never "zero"
            # (DECISIONS §65, applied here as in ANS-4).
            return CheckResult("ANS-1", title, "not_assessed",
                               f"Not assessed: no cited URL on this site in the data supplied, but the data is "
                               f"{evidence['input_completeness']}. This is not 'zero citations'.", [], evidence)
        return CheckResult("ANS-1", title, "observed",
                           f"Zero cited URLs on this site in the data supplied ({data.freshness()}).", [], evidence)
    summary = (f"{len(findings)} cited URL(s) fail a site check, {len(consolidated)} hand their citation to a live "
               f"page (redirect, or canonical with the same content), {len(healthy)} are healthy"
               + (f", {len(unresolved)} could not be followed" if unresolved else "")
               + (f", {len(unchecked)} could not be checked (see coverage)" if unchecked else "")
               + f", across {len(data.engines)} engine(s): {', '.join(data.engines)}. {data.freshness()}.")
    return CheckResult("ANS-1", title, _status(findings), summary, findings, evidence)


# -- ANS-2 ---------------------------------------------------------------------

PRICE_KINDS = {"price", "plan", "pricing", "plan_name"}


def _sentence_with(text: str, needle: str) -> str | None:
    """The sentence of `text` containing `needle` (for answer excerpts)."""
    for sentence in SENTENCE.split(text or ""):
        if needle and needle.casefold() in sentence.casefold():
            return sentence.strip()[:300]
    return None


def _page_quote(analysis: dict, needle: str) -> str | None:
    """The page's own line containing `needle`: text nodes are quoted one at a time, never run together."""
    if not needle:
        return None
    for block in analysis.get("_text_blocks", []):
        if needle.casefold() in block.casefold():
            return _sentence_with(block, needle) or block.strip()[:300]
    return None


def _derived_price_claims(record: dict) -> list[dict]:
    """No LLM-extracted claims: read prices out of the answer text with the T0 tokenizer (STR)."""
    answer = record.get("answer_excerpt") or ""
    return [{"text": token["text"], "kind": "price", "value": str(token["value"]), "derived": True}
            for token in price_tokens(answer)]


def _input_completeness(data: CitationData) -> str:
    """Whether the citation input can support "this site was (not) cited". Recorded on every ANS-1 result."""
    sample = data.sample or {}
    reasons = []
    if sample.get("hasMore") is True or (isinstance(sample.get("returned"), int) and isinstance(sample.get("total"), int)
                                         and sample["returned"] < sample["total"]):
        reasons.append(f"paged: {sample.get('returned', '?')} of {sample.get('total', '?')} record(s) returned")
    if data.invalid_records and not data.records and not data.off_site:
        reasons.append(f"every one of {len(data.invalid_records)} record(s) was invalid")
    return ("incomplete: " + "; ".join(reasons)) if reasons else "complete as far as the file shows"


_WORD4 = re.compile(r"[^\W\d_]{4,}")
_NUMBER = re.compile(r"\d[\d.,]*")


def _best_sentence(analysis: dict, claim_text: str) -> str | None:
    """The page sentence sharing the most significant words (4+ letters) with the claim, if enough do."""
    wanted = set(_WORD4.findall(claim_text.casefold()))
    if not wanted:
        return None
    best, score = None, 0
    for block in analysis.get("_text_blocks", []):
        for sentence in SENTENCE.split(block):
            n = len(wanted & set(_WORD4.findall(sentence.casefold())))
            if n > score:
                best, score = sentence.strip(), n
    return best[:300] if best and score >= min(2, len(wanted)) else None


def compare_claim(claim: dict, analysis: dict) -> dict:
    """One answer claim against one page view. Deterministic (T0) unless the claim carries a comparison made
    upstream, which is recorded as model-assisted. Verdicts: matches | contradicted | absent.

    "Absent" is not a contradiction: the page does not state it (or states it in other words), and the answer
    may come from another source. Only "contradicted" means the page states a different value.
    """
    upstream = claim.get("comparison") if isinstance(claim.get("comparison"), dict) else None
    if upstream and upstream.get("verdict") in ("matches", "contradicted", "absent"):
        return {"verdict": upstream["verdict"], "page_sentence": upstream.get("page_quote"),
                "page_value": upstream.get("page_value"),
                "comparison_mode": f"supplied upstream ({upstream.get('method') or 'model-assisted'}); not re-checked"}
    kind = (claim.get("kind") or "other").casefold()
    value = claim.get("value")
    text = analysis.get("_visible_text", "")
    sentence = _best_sentence(analysis, claim["text"])
    if kind in PRICE_KINDS and value is not None:
        wanted = parse_number(str(value))
        page_prices = price_tokens(text)
        if any(wanted is not None and t["value"] == wanted for t in page_prices):
            return {"verdict": "matches", "page_sentence": sentence, "comparison_mode": "price tokens (T0)",
                    "page_value": str(value)}
        near = price_tokens(sentence) if sentence else []
        if near:
            return {"verdict": "contradicted", "page_sentence": sentence, "page_value": [t["text"] for t in near],
                    "comparison_mode": "price in the page sentence that matches the claim's words (T0)",
                    "page_shows": sorted({t["text"] for t in page_prices})[:10]}
        if page_prices:
            return {"verdict": "contradicted", "page_sentence": _page_quote(analysis, page_prices[0]["text"]),
                    "page_value": sorted({t["text"] for t in page_prices})[:10],
                    "page_shows": sorted({t["text"] for t in page_prices})[:10],
                    "comparison_mode": "prices anywhere on the page (T0); none equals the claim, and which one is "
                                       "this plan's price is assumed"}
        return {"verdict": "absent", "page_sentence": sentence, "comparison_mode": "price tokens (T0)",
                "page_shows": "no price in the page text"}
    if value is not None and _NUMBER.fullmatch(str(value).strip()):
        tokens = set(_NUMBER.findall(text))
        if str(value).strip() in tokens:
            return {"verdict": "matches", "page_sentence": _page_quote(analysis, str(value)), "page_value": str(value),
                    "comparison_mode": "number on the page (T0)"}
        others = [n for n in _NUMBER.findall(sentence or "") if len(n) == len(str(value).strip())]
        if others:
            return {"verdict": "contradicted", "page_sentence": sentence, "page_value": others,
                    "comparison_mode": "number in the page sentence that matches the claim's words (T0)"}
        return {"verdict": "absent", "page_sentence": sentence, "comparison_mode": "number on the page (T0)"}
    needle = str(value) if value is not None else claim["text"]
    found = needle.casefold() in text.casefold()
    return {"verdict": "matches" if found else "absent", "page_sentence": _page_quote(analysis, needle[:60]) or sentence,
            "comparison_mode": "text containment (T0); a paraphrase on the page reads as absent"}


def ans2_stale_facts(result: CrawlResult, cfg: CrawlConfig, data: CitationData) -> CheckResult:
    title = "Stale or wrong facts in answers vs the live site"
    empty = _no_data("ANS-2", title, data)
    if empty:
        return empty
    key_urls = set(key_page_urls(result, cfg))
    render = getattr(result, "render", None)
    contradicted: dict[str, list[dict]] = defaultdict(list)
    absent, only_rendered = [], []
    compared = not_compared = derived_only = 0
    for record in data.records:
        view = _site_view(record["url"], result, cfg, data)
        analysis = view.get("analysis")
        if not analysis:
            not_compared += 1
            continue
        rendered_entry = (render.pages.get(record["url"]) if render else None) or {}
        rendered = rendered_entry.get("rendered") if rendered_entry.get("ok") else None
        claims = record["claims"]
        if not claims:
            claims = _derived_price_claims(record)
            derived_only += len(claims)
        for claim in claims:
            kind = (claim.get("kind") or "other").casefold()
            compared += 1
            result_row = compare_claim(claim, analysis)
            source = "raw HTML"
            if result_row["verdict"] == "absent" and rendered:
                on_rendered = compare_claim(claim, rendered)
                if on_rendered["verdict"] != "absent":
                    result_row, source = on_rendered, "rendered view only (the raw HTML does not show it; see RND-1)"
            row = {"engine": record["engine"], "model": record.get("model"), "cited_at": record.get("cited_at"),
                   "url": record["url"], "prompt": record.get("prompt"),
                   "answer_says": claim["text"][:300],
                   "answer_sentence": _sentence_with(record.get("answer_excerpt") or "", claim["text"][:40])
                                      or (record.get("answer_excerpt") or "")[:300],
                   "claim_kind": kind, "claim_value": claim.get("value"),
                   "claim_source": "derived by Maya from the answer text (T0)" if claim.get("derived")
                                   else "supplied upstream (extracted from the answer, T4)",
                   "derived_by_maya": bool(claim.get("derived")), "page_view": source, **result_row}
            if result_row["verdict"] == "contradicted":
                contradicted["price" if kind in PRICE_KINDS else "other"].append(row)
            elif result_row["verdict"] == "absent":
                absent.append(row)
            elif source != "raw HTML":
                only_rendered.append(row)
    findings = []
    fix_note = ("How to fix is Hypothesis: updating the cited page is expected to correct retrieval-backed answers, "
                "but that effect is unproven.")
    for kind, rows in contradicted.items():
        severity = Severity.S2 if kind == "price" else Severity.S3
        urls = sorted({r["url"] for r in rows})
        label = "a price or plan" if kind == "price" else "a fact"
        notes = [CITATION_NOTE, fix_note,
                 "Severity describes the consequence if the conflict is real; the confidence label is separate.",
                 "Rationale is Self-evident harm (spec §2.3): the wrong statement in the answer is itself the harm, "
                 "so the Hypothesis cap does not apply.",
                 "Estimated: the answer claim comes from sampled, upstream data. The page side is quoted from Maya's "
                 "own fetch; each row names how the two were compared (comparison_mode)."]
        if any(r["derived_by_maya"] for r in rows):
            notes.append("Rows marked derived_by_maya were read out of the answer text by Maya's price tokenizer "
                         "(T0), not extracted by an LLM; supply claims in the citation file for full coverage.")
        findings.append(Finding(
            "ANS-2", f"{len(rows)} answer(s) state {label} that the cited page contradicts", severity,
            Confidence.ESTIMATED, Rationale.SELF_EVIDENT.value, sorted({r["engine"] for r in rows}), scope_for(urls),
            {"conflicts": rows[:40], "citation_data": data.freshness()},
            "answers repeat what the page currently says",
            "Check each row: if the page is out of date, update it (and its STR-4 markup and lastmod). If the page "
            "is right, the answer is stale or came from another source.",
            cost_tier="T4", importance_tier=_tier(urls, key_urls), notes=notes))
    review_items = []
    if absent:
        urls = sorted({r["url"] for r in absent})
        review_items.append(ReviewItem(
            "ANS-2", f"{len(absent)} answer claim(s) state something the cited page does not show",
            "The page neither confirms nor contradicts these claims: it may say it in other words, the answer may "
            "draw on another source, or the page may have dropped the fact. None of that is a proven conflict, so "
            "there is no severity; a person should read each answer sentence against the page.",
            Confidence.ESTIMATED, sorted({r["engine"] for r in absent}), scope_for(urls),
            {"claims": absent[:40], "citation_data": data.freshness()},
            "Read each claim against the cited page. If the page should state it, add it; if the answer is wrong, "
            "that is a content question for the page the engine should cite.", importance_tier=_tier(urls, key_urls)))
    evidence = {"citation_data": data.freshness(), "claims_compared": compared,
                "verdicts": {"contradicted": sum(len(v) for v in contradicted.values()), "absent": len(absent),
                             "matches": compared - sum(len(v) for v in contradicted.values()) - len(absent)},
                "matches_only_in_rendered_view": only_rendered[:20],
                "records_without_a_readable_cited_page": not_compared,
                "claims_derived_by_maya_because_none_were_supplied": derived_only,
                "llm_claim_extraction": "not built here: claims come from the citation file (T4 upstream)",
                "comparison": "deterministic (T0) for prices and numbers against the page sentence that matches the "
                              "claim's words; text containment otherwise; a comparison supplied upstream is used as "
                              "given and labelled model-assisted",
                "engines": data.engines, "citations_per_engine": {r["engine"]: r["citations"] for r in _citation_rows(data.records)}}
    if not compared:
        without_text = sum(1 for r in data.records if not r["claims"] and not r.get("answer_excerpt"))
        why = (f"{without_text} of {len(data.records)} record(s) carry neither claims nor answer text, so there is "
               "nothing to compare. Maya's citation API returns no answer text today (README), so this check needs "
               "claims in the citation file."
               if without_text else "no claims in the citation file and no prices in the answer text")
        return CheckResult("ANS-2", title, "not_assessed", f"Not assessed: {why}", [], evidence)
    summary = (f"{len(findings)} finding(s) and {len(review_items)} review item(s) from {compared} claim(s) across "
               f"{len(data.engines)} engine(s). {data.freshness()}." if findings or review_items
               else f"All {compared} claim(s) match the cited pages. {data.freshness()}.")
    return CheckResult("ANS-2", title, _status(findings, review_items), summary, findings, evidence, [], review_items)


# -- ANS-3 ---------------------------------------------------------------------

def ans3_attribution(data: CitationData) -> CheckResult:
    return CheckResult(
        "ANS-3", "Retrieval vs training attribution note", "not_assessed",
        "Cut from v1 (spec §8 F7): citation-only data holds mentions that came with a citation, so there are no "
        "uncited mentions to compare against. It returns only if Maya stores full answer records.",
        evidence={"v1_status": "cut", "needed_to_build": "answer records that mention the brand with zero citations"})


# -- ANS-4 / ANS-5 -----------------------------------------------------------
# Both read the cited-domain export (--citation-domains), not the per-citation file. Both are
# observations: they measure what the engines did, which is not a defect in the site, so neither
# invents a severity for a number moving. The one finding ANS-4 raises is an engine that cites
# this topic and never this site — and even that is Info, because "no citations yet" has many
# causes and this tool can only see some of them.
# Answer engine -> the tokens that decide whether it can find and read a page for an answer: search and live-fetch
# tokens only (B13). A training token (GPTBot, ClaudeBot) changes what a model learns, not what an engine cites, and
# Google documents that Google-Extended does not affect AI Overviews or AI Mode. Gemini keeps Google-Extended: Google
# documents it as the control for grounding Gemini apps' answers, which is the citing this check is about.
ENGINE_CRAWLERS = {
    "chatgpt": ("OAI-SearchBot", "ChatGPT-User"),
    "perplexity": ("PerplexityBot", "Perplexity-User"),
    "gemini": ("Googlebot", "Google-Extended"),
    "google-ai-overview": ("Googlebot",),
    "google-ai-mode": ("Googlebot",),
    "claude": ("Claude-SearchBot", "Claude-User"),
    "copilot": ("Bingbot",),
}
NOT_SOV = ("This is a share of cited source domains, which is not Maya's Share of Voice: that counts brand "
           "mentions in answer text across a curated competitor set, while this counts cited domains including "
           "image CDNs and reference sites. On a real project the two differed by about 5x. Both are correct; "
           "they measure different things. Do not present this number as Share of Voice.")


def _no_domain_data(check_id: str, title: str, domains: CitationDomains) -> CheckResult | None:
    if domains.path is None:
        return CheckResult(check_id, title, "not_assessed",
                           "Not assessed: no cited-domain data (--citation-domains). This is 'no data', not "
                           "'no citations'.", evidence={"citation_domains": "none supplied"})
    if not domains.loaded:
        return CheckResult(check_id, title, "not_assessed",
                           f"Not assessed: the cited-domain file could not be read ({domains.error}).",
                           evidence={"citation_domains_file": domains.path, "error": domains.error})
    if domains.site_row() is None:
        return CheckResult(check_id, title, "not_assessed",
                           "Not assessed: the export lists no row for this site, so there is nothing to compare. "
                           "A truncated export can omit the site even when it is cited; re-export with a higher "
                           "limit or a domain filter before reading anything into this.",
                           evidence={"citation_domains_file": domains.path, "rows_returned": domains.rows_returned,
                                     "rows_total": domains.rows_total, "site_domain": domains.site_domain})
    return None


def _blocked_tokens_for(engine: str, site_checks: list[CheckResult]) -> list[dict[str, Any]]:
    """ACC-2/ACC-6 findings naming a crawler this engine uses, so ANS-4 points at them instead of re-reporting."""
    tokens = {t.casefold() for t in ENGINE_CRAWLERS.get(engine, ())}
    if not tokens:
        return []
    out = []
    for check in site_checks:
        if check.check_id not in ("ACC-2", "ACC-6"):
            continue
        for finding in check.findings:
            # Only the tokens ACC-2/ACC-6 found blocked (B13). A title that names a token is not proof of a block: the
            # policy-mismatch and group-precedence notes name tokens robots.txt allows.
            named = {t.casefold() for t in finding.evidence.get("blocked_tokens") or [] if isinstance(t, str)}
            if not (named & tokens):
                continue
            out.append({"check_id": finding.check_id, "title": finding.title,
                        "severity": finding.severity, "finding_id": finding.id})
    return out


def ans4_engine_coverage(result: CrawlResult, cfg: CrawlConfig, domains: CitationDomains,
                         site_checks: list[CheckResult]) -> CheckResult:
    title = "Answer-engine coverage of this site"
    early = _no_domain_data("ANS-4", title, domains)
    if early:
        return early

    site = domains.site_row()
    # Engines that cited anything at all in this export, so "engine did not cite the site" can be told
    # apart from "the export never covered that engine".
    engines_seen: dict[str, int] = defaultdict(int)
    for row in domains.rows:
        for engine, count in row["by_model"].items():
            engines_seen[engine] += count

    observations, findings = [], []
    site_total = sum(site["by_model"].values()) or site["mentions"]
    for engine in sorted(engines_seen):
        cited = site["by_model"].get(engine, 0)
        observation = {"engine": engine, "citations_of_this_site": cited,
                       "share_of_this_site's_citations": round(cited / site_total * 100, 1) if site_total else None,
                       "engine_active_in_export": engines_seen[engine] > 0}
        # A per-engine share against other domains needs a per-engine denominator, which a truncated
        # export cannot give: summing the listed rows alone would overstate the site on every engine.
        if domains.engine_totals_complete:
            observation["share_of_engine's_cited_domains"] = round(cited / engines_seen[engine] * 100, 1)
        else:
            observation["share_of_engine's_cited_domains"] = None
            observation["why_no_share"] = (f"export lists {domains.rows_returned} of {domains.rows_total} domains; "
                                           "a per-engine denominator from the listed rows would overstate this site")
        observations.append(observation)

        if cited == 0 and engines_seen[engine] > 0:
            blocked = _blocked_tokens_for(engine, site_checks)
            notes = [NOT_SOV]
            if blocked:
                # One report per root cause: ACC-2/ACC-6 owns the block, this adds what it cost.
                notes.append(f"{blocked[0]['check_id']} reports that this engine's crawler is disallowed; that "
                             "finding owns the cause, this one records that the engine cites the topic and not "
                             "this site.")
            findings.append(Finding(
                check_id="ANS-4",
                title=f"{engine} cited {engines_seen[engine]} domain-mentions on this topic and none from this site",
                severity=Severity.INFO, confidence=Confidence.ESTIMATED, rationale=Rationale.HYPOTHESIS,
                engines=[engine], scope=scope_for([result.origin], sitewide=True),
                evidence={"engine": engine, "citations_of_this_site": 0,
                          "engine_mentions_in_export": engines_seen[engine],
                          "site_domain": domains.site_domain, "period_days": domains.period_days,
                          "export_truncated": domains.truncated,
                          "rows_returned": domains.rows_returned, "rows_total": domains.rows_total,
                          "related_access_findings": blocked},
                expected="A site cited by comparable engines is usually cited by this one too.",
                how_to_fix=("Check this engine's crawler against ACC-2 and ACC-6 first. Absence has many causes "
                            "this tool cannot see — the engine may not cover this language or market — so treat "
                            "it as somewhere to look, not as a defect."),
                cost_tier="T4", notes=notes, launch_gated=["LG-30"]))

    evidence = {"site_domain": domains.site_domain, "citations_of_this_site": site["mentions"],
                "engines_in_export": sorted(engines_seen), "period_days": domains.period_days,
                "export_truncated": domains.truncated, "rows_returned": domains.rows_returned,
                "rows_total": domains.rows_total, "total_mentions_all_domains": domains.total_mentions,
                "unique_domains": domains.unique_domains, "freshness": domains.freshness(),
                "not_share_of_voice": NOT_SOV}
    if domains.total_mentions:
        evidence["share_of_all_cited_domain_mentions_pct"] = round(site["mentions"] / domains.total_mentions * 100, 2)

    covered = [e for e in engines_seen if site["by_model"].get(e, 0) > 0]
    summary = (f"Cited by {len(covered)} of {len(engines_seen)} engine(s) present in the export "
               f"({', '.join(covered) or 'none'}); {site['mentions']} domain-mentions over "
               f"{domains.period_days or 'an unstated number of'} day(s).")
    return CheckResult("ANS-4", title, _status(findings), summary, findings, evidence, observations)


def ans5_offsite_presence(domains: CitationDomains) -> CheckResult:
    title = "Where this brand is cited away from its own site"
    early = _no_domain_data("ANS-5", title, domains)
    if early:
        return early

    site = domains.site_row()
    by_class: dict[str, list[dict]] = defaultdict(list)
    for row in domains.rows:
        by_class[row["class"]].append(row)

    observations = []
    for name in CLASSES:
        rows = by_class.get(name, [])
        if not rows:
            continue
        observations.append({
            "class": name, "domains": len(rows), "mentions": sum(r["mentions"] for r in rows),
            "top": [{"domain": r["domain"], "mentions": r["mentions"],
                     "engines": sorted(r["by_model"])} for r in rows[:5]]})

    # "other" is the interesting class: commercial sites that are neither this site, an engine's own
    # asset host, a reference work, nor a profile page. Those are the ones a brand competes with.
    others = by_class.get("other", [])
    ahead = [r for r in others if r["mentions"] > site["mentions"]]
    evidence = {"site_domain": domains.site_domain, "citations_of_this_site": site["mentions"],
                "classified": {name: len(by_class.get(name, [])) for name in CLASSES if by_class.get(name)},
                "commercial_domains_cited_more_than_this_site": [
                    {"domain": r["domain"], "mentions": r["mentions"]} for r in ahead[:10]],
                "export_truncated": domains.truncated, "rows_returned": domains.rows_returned,
                "rows_total": domains.rows_total, "period_days": domains.period_days,
                "freshness": domains.freshness(),
                "classification_is_unvalidated": ("Domains are sorted by a hand-written list of known "
                                                  "infrastructure, reference and directory hosts (LG-29). It is a "
                                                  "starting point, not a taxonomy: read the rows, not the labels."),
                "not_share_of_voice": NOT_SOV}
    summary = (f"{len(others)} commercial domain(s) in this export are cited alongside this site"
               + (f"; {len(ahead)} of them more often than the site itself" if ahead else "")
               + (f". The export lists {domains.rows_returned} of {domains.rows_total} domains, so this is the "
                  "top of the list, not all of it." if domains.truncated else "."))
    return CheckResult("ANS-5", title, "observed", summary, [], evidence, observations)


def run_answer_checks(result: CrawlResult, cfg: CrawlConfig, site_checks: list[CheckResult]) -> list[CheckResult]:
    data = result.citations if getattr(result, "citations", None) is not None else CitationData()
    domains = result.citation_domains if getattr(result, "citation_domains", None) is not None else CitationDomains()
    return settle_all([ans1_cited_url_health(result, cfg, data, site_checks), ans2_stale_facts(result, cfg, data),
                       ans3_attribution(data), ans4_engine_coverage(result, cfg, domains, site_checks),
                       ans5_offsite_presence(domains)], result)
