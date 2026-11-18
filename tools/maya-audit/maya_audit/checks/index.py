"""IDX-1 to IDX-10: crawlability and indexability checks (spec §5 IDX).

Same rules as ACC: severity comes only from what is broken; key pages affect
priority only. Harm that cannot be classified becomes a visible review item.
"""

from __future__ import annotations

import re
import shlex
from collections import Counter as Counter_, defaultdict
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from ..access_data import homepage_url, key_page_urls
from ..analysis import compare_content, fold_text, sketch_similarity, text_sketch
from urllib.parse import parse_qsl, unquote, urlsplit

from ..config import (MIN_MAIN_WORDS_TO_COMPARE, TRACKING_PARAMETER_PREFIXES, TRACKING_PARAMETERS, CrawlConfig)
from ..main_content import BASIS as MAIN_CONTENT_BASIS
from ..main_content import main_words, repeated_blocks
from ..coverage import settle_all
from ..directives import noindex_directives
from ..findings import CheckResult, Finding, Rationale, ReviewItem, Severity, scope_for
from ..html_links import is_html
from ..index_data import (HTTP_SERVED_OUTCOMES, LOOPS, NOT_LIVE_KINDS, IndexData, address_pairs, canonical_elsewhere,
                          canonical_variant, cloudflare_email_pages, crawl_redirects, draft_pages, edge_machinery,
                          effective_canonical, guess_words, http_redirect_outcomes, malformed, misplaced_links,
                          not_percent_encoded, page_kind, page_words, redirect_verdict, redirect_walks, row_kind)
from ..external_links import REASONS
from ..sitemap import GUESSED as SITEMAP_GUESSED
from ..urls import non_page_kind
from ..perf_data import attempts_by_url, counted, failed
from ..models import Confidence, CrawlResult, FetchClass, StopReason
from ..urls import listing_view_of, normalize_url, registrable_domain, same_origin
from .access import _status, _tier, _with_intent

ALL_ENGINES = ["all answer engines (any automated fetcher)"]
INDEX_ENGINES = ["Google AI Overviews / AI Mode", "Microsoft Copilot (Bing index)"]
GOOGLE = "Google AI Overviews / AI Mode"


def _index(result: CrawlResult) -> IndexData:
    assert result.index is not None, "run the audit through maya_audit.audit.run_audit"
    return result.index


def _curl(url: str, cfg: CrawlConfig) -> str:
    return f"curl -i -A {shlex.quote(cfg.user_agent)} {shlex.quote(url)}"


def _readable_html(page) -> bool:
    return page.readable_document() and is_html(page.content_type) and page.analysis is not None


def _inlinks(result: CrawlResult) -> dict[str, list[dict]]:
    inbound: dict[str, list[dict]] = defaultdict(list)
    for page in result.pages:
        for edge in page.outlinks:
            inbound[edge["target"]].append({"source": page.url, "anchor": edge["anchor"]})
        if page.redirect_location:
            inbound[page.redirect_location].append({"source": page.url, "anchor": "(redirect)"})
    return inbound


# -- IDX-1 -------------------------------------------------------------------

def soft_404_verdict(probe: dict, result: CrawlResult) -> dict:
    """What the answer to the made-up address means: {"soft_404", "kind", "assessed", "text"}."""
    if not probe.get("sent"):
        return {"soft_404": False, "kind": "not_sent", "assessed": False, "text": f"not run ({probe.get('reason')})"}
    status, target = probe.get("status"), probe.get("redirect_location")
    homes = {u.rstrip("/") for u in (homepage_url(result), result.start_url, result.origin) if u}
    if status in (404, 410):
        return {"soft_404": False, "kind": "ok", "assessed": True, "text": f"a made-up address answers {status}, as it should"}
    if status and 200 <= status < 300:
        return {"soft_404": True, "kind": "answers_200", "assessed": True, "text": f"a made-up address answers {status}"}
    if status and 300 <= status < 400 and target and target.rstrip("/") in homes:
        return {"soft_404": True, "kind": "redirect_to_homepage", "assessed": True,
                "text": f"a made-up address redirects ({status}) to the homepage"}
    from .team_rules import error_page
    if status and 300 <= status < 400 and target and error_page(target):
        # DECISIONS 343: its own finding (idx1.error_redirect), with every crawled address that does the same
        return {"soft_404": False, "kind": "redirect_to_error_page", "assessed": True,
                "text": f"a made-up address redirects ({status}) to an error page ({target}) instead of answering 404"}
    if status and 300 <= status < 400:
        return {"soft_404": False, "kind": "redirect_elsewhere", "assessed": False,
                "text": f"a made-up address redirects ({status}) to {target}; the redirect was not followed, so where "
                        "it ends is not known"}
    return {"soft_404": False, "kind": "inconclusive", "assessed": False,
            "text": f"a made-up address answered {status if status else probe.get('error')}, which does not settle it"}


EMPTY_FIX = ("Reproduce the recorded empty GET responses for the affected URLs and the same client. "
             "Establish the intended page content before choosing a remedy; no server, plugin or cache cause is established.")
EMPTY_PROBE_FIX = ("Corroborate each recorded empty GET within policy and request budgets. Establish intended purpose "
                   "before changing content, links or sitemap entries; missing corroboration proves neither persistent failure nor recovery.")
# First review C1/C2: empty to Maya's own user agent twice, content to a browser user agent.
BOT_EMPTY_TITLE = ("{n} page(s) answer with an empty page to automated clients only (under {limit} bytes); a browser gets "
                   "content")
BOT_EMPTY_FIX = ("Find what sends automated clients an empty answer (a bot filter, a firewall or CDN rule, a cache "
                 "variant keyed on the user agent) and let crawlers that should read the site get the same page a "
                 "browser gets. Check with ACC-4's user-agent comparison and the site's own logs.")
ERROR_TEXT_FIX = ("Turn off error display on the live server and log errors instead (PHP: display_errors = Off; WordPress: "
                  "WP_DEBUG_DISPLAY false), then fix the error itself.")
# Empty-response severity follows evidence strength and confirmed page importance (decision241, LG-75).


def _sitemap_rows(data) -> list[dict]:
    """The sitemap check's light requests (maya_audit.index_data.check_sitemap_urls), or none."""
    check = getattr(data, "sitemap_check", None)
    return list(getattr(check, "rows", None) or [])


def _llms_rows(data) -> list[dict]:
    """ACC-8's light requests to the links of llms.txt (maya_audit.access_data.check_llms_links), or none."""
    check = getattr(data, "sitemap_check", None)
    return list(getattr(check, "llms_rows", None) or [])


def is_empty(page) -> bool:
    return bool((page.analysis or {}).get("empty_response"))


def _empty_pages(result: CrawlResult, cfg: CrawlConfig, data: IndexData, key_urls: set[str],
                 observations: list[dict]) -> list[Finding]:
    """Separate successful empty observations, unavailable verification and content recovery."""
    refetched = {r["url"]: r["refetch"] for r in data.refetches}
    evidence = {}
    for p in result.pages:
        if is_empty(p):
            evidence.setdefault(p.url, []).append({"source": "native_crawl", "method": "GET", "status": p.status,
                "body_bytes": p.body_bytes, "requested_at": p.requested_at, "empty": True})
    for source, rows in (("sitemap_probe", _sitemap_rows(data)), ("llms_probe", _llms_rows(data))):
        for row in rows:
            if row.get("empty") and row.get("fetch_class") == FetchClass.OK.value:
                evidence.setdefault(row["url"], []).append({"source": source, "method": "GET", "status": row.get("status"),
                    "body_bytes": row.get("bytes"), "requested_at": row.get("requested_at"), "empty": True})
    retained = []
    for url, attempts in evidence.items():
        content = [p for p in result.pages if p.url == url and p.status and 200 <= p.status < 300
                   and p.fetch_class == FetchClass.OK and p.analysis and not is_empty(p)]
        if content:
            observations.append({"url": url, "metric": "mixed empty and content-bearing native responses",
                                 "attempts": attempts + [{"method": "GET", "source": "native_crawl", "status": p.status,
                                 "body_bytes": p.body_bytes, "requested_at": p.requested_at} for p in content]})
            continue
        again = refetched.get(url)
        if again is not None:
            attempts.append({"source": "idx_refetch", "method": "GET", "status": again.get("status"),
                "error": again.get("error"), "body_bytes": again.get("body_bytes"),
                "requested_at": again.get("requested_at"), "empty": again.get("empty_response")})
            if (not again.get("error") and again.get("status") and 200 <= again["status"] < 300
                    and again.get("empty_response") is False and (again.get("readable_html") is True or again.get("analysis"))):
                observations.append({"url": url, "metric": "empty on some attempts only: another attempt contained HTML content",
                                     "attempts": attempts})
                continue
        successful_empty = [a for a in attempts if a.get("empty") and a.get("status")
                            and 200 <= a["status"] < 300 and not a.get("error")]
        # One stored representation repeated twice is not a second independent observation. The IDX-1 refetch is always
        # a request of its own, so it counts even when the clock gave it the crawl's timestamp (Windows' clock ticks in
        # ~16 ms steps; two requests to a fast site can share one, DECISIONS 274).
        distinct = {(a["source"] == "idx_refetch", a["requested_at"]) for a in successful_empty if a.get("requested_at")}
        repeated = len(distinct) >= 2
        retained.append({"url": url, "status": attempts[0]["status"], "body_bytes": attempts[0]["body_bytes"],
                         "requested_at": attempts[0]["requested_at"], "method": "GET", "attempts": attempts, "refetch": refetched.get(url),
                         "repeated_empty": repeated, "importance": "key" if url in key_urls or url == homepage_url(result) else "unknown",
                         "reproduce": _curl(url, cfg)})
    findings = []
    # First review C1/C2: two empty answers to Maya's own user agent are one client's view. A few of those pages were
    # asked once more as a browser (index_data.empty_browser_check). A sampled page follows its own browser answer:
    # content there means the site sends nothing to automated clients only, an access problem (S3), not an empty page;
    # empty there too confirms the verdict (S1 key / S2 other, DECISIONS 204). A page not asked follows the sample only
    # when every answer agrees; with no answer, or a mixed sample, it is not confirmed by another client and stays S3.
    check = getattr(data, "empty_browser_check", None) or {}
    sent = [a for a in check.get("answers") or [] if a.get("sent")]
    by_url = {a["url"]: a for a in sent}
    all_content = bool(sent) and all(a.get("content") for a in sent)
    all_empty = bool(sent) and all(a.get("empty_response") for a in sent)
    browser_evidence = {"user_agent": check.get("user_agent"), "purpose": check.get("purpose"), "cap": check.get("cap"),
                        "answers": check.get("answers") or [], "reason": check.get("reason"),
                        "verdict": ("a browser got content: the empty answers are for automated clients only" if all_content
                                    else "a browser got an empty page too" if all_empty
                                    else "a browser got content on some sampled pages and an empty page on others"
                                    if sent else "not asked as a browser: not confirmed by another client")}
    for row in retained:
        answer = by_url.get(row["url"])
        if not row["repeated_empty"]:
            row["_state"] = "single"
        elif answer is not None:
            row["_state"] = "bot" if answer.get("content") else "confirmed" if answer.get("empty_response") else "unconfirmed"
        else:
            row["_state"] = "bot" if all_content else "confirmed" if all_empty else "unconfirmed"
    bot_rows = [r for r in retained if r["_state"] == "bot"]
    if bot_rows:
        urls = [r["url"] for r in bot_rows]
        findings.append(Finding(
            "IDX-1", BOT_EMPTY_TITLE.format(n=len(urls), limit=cfg.empty_response_max_bytes), Severity.S3,
            Confidence.ESTIMATED, Rationale.SELF_EVIDENT.value, ALL_ENGINES, scope_for(urls),
            {"pages": bot_rows, "limit": cfg.empty_response_max_bytes, "browser_check": browser_evidence,
             "observation_strength": "repeated_empty_to_maya_content_to_a_browser", "unique_affected_urls": len(urls),
             "homepage_or_key_page": [r["url"] for r in bot_rows if r["importance"] == "key"],
             "rule": "empty twice to Maya's own user agent, and its own browser answer had content (a page not asked: "
                     "every sampled browser answer had content): the site treats automated clients differently (S3)"},
            "every client, automated or not, gets the page's content", BOT_EMPTY_FIX,
            importance_tier=_tier(urls, key_urls),
            notes=["Some of these pages were asked once more with a browser user agent (browser_check in the evidence); a "
                   "page not asked is judged from that sample (Estimated).",
                   "Measured with a browser user agent from Maya's own address; what a given AI crawler gets is not "
                   "measured here (ACC-4 compares user agents)."]))
    # Do not merge evidence strengths: single probes remain consequential observations, not universal failures.
    for state, key in (("confirmed", True), ("confirmed", False), ("unconfirmed", None), ("single", None)):
        rows = [r for r in retained if r["_state"] == state and (key is None or (r["importance"] == "key") == key)]
        if not rows:
            continue
        urls = [r["url"] for r in rows]
        important = [r["url"] for r in rows if r["importance"] == "key"]
        repeated, confirmed = state != "single", state == "confirmed"
        severity = Severity.S1 if confirmed and important else Severity.S2 if confirmed else Severity.S3
        strength = ("repeated_empty" if confirmed else "repeated_empty_mixed_browser_sample" if repeated and sent
                    else "repeated_empty_same_client_only" if repeated else "single_probe_or_missing_corroboration")
        findings.append(Finding("IDX-1", f"{len(urls)} page(s) answer with an empty page (under {cfg.empty_response_max_bytes} bytes)",
            severity, Confidence.VERIFIED if repeated else Confidence.ESTIMATED, Rationale.SELF_EVIDENT.value,
            ALL_ENGINES, scope_for(urls), {"pages": rows, "limit": cfg.empty_response_max_bytes,
                "observation_strength": strength,
                "unique_affected_urls": len(urls), "repeated_empty_urls": len(urls) if repeated else 0,
                "homepage_or_key_page": important, "evidence_complete": True,
                **({"browser_check": browser_evidence} if repeated else {}),
                "rule": "S1 only for repeated empty GETs on homepage/key pages, confirmed empty to a browser user agent; "
                        "other confirmed repeated S2; single, or repeated to Maya's client only, S3. URL share alone never "
                        "establishes business impact."},
            "intended pages serve their content for the tested client", EMPTY_FIX if repeated else EMPTY_PROBE_FIX,
            importance_tier=_tier(urls, key_urls), notes=["Observed for the recorded client and time; intended purpose and other clients may differ.",
                ("Repeated empty responses, a browser user agent got an empty page too." if confirmed else
                 "Repeated empty responses to Maya's own user agent; not confirmed with another client (browser_check in "
                 "the evidence says why)." if repeated else
                 "One empty observation or unavailable corroboration; not a confirmed persistent failure.")]))
    for row in retained:
        row.pop("_state", None)
    return findings


def _error_text(result: CrawlResult, cfg: CrawlConfig, key_urls: set[str]) -> list[Finding]:
    """Pages that show a server error message with the server's file paths (DECISIONS 204): in Maya's own crawl, and
    in the answers to the ACC-4 user-agent check (DECISIONS 205). The quoted line has the account folder masked."""
    rows: dict[str, dict] = {}
    for page in result.pages:
        if page._error_text:
            rows.setdefault(page.url, {"url": page.url, "status": page.status, "seen_by": "Maya's crawler",
                                       "requested_at": page.requested_at, **page._error_text,
                                       "reproduce": _curl(page.url, cfg)})
    for row in _sitemap_rows(getattr(result, "index", None)):
        if row.get("error_text") and row["url"] not in rows:
            rows[row["url"]] = {"url": row["url"], "status": row["status"], "seen_by": "the sitemap check (one light request)",
                                "requested_at": row["requested_at"], **row["error_text"], "reproduce": _curl(row["url"], cfg)}
    access = getattr(result, "access", None)
    for pair in ((getattr(access, "ua_check", None) or {}).get("pairs") or []):
        for answer in (pair.get("browser"), pair.get("googlebot")):
            if answer and answer.get("error_disclosure") and pair["url"] not in rows:
                rows[pair["url"]] = {"url": pair["url"], "status": answer["status"],
                                     "seen_by": f"a request with the {answer['label']} user agent (ACC-4)",
                                     "requested_at": answer["requested_at"], **answer["error_disclosure"]}
    if not rows:
        return []
    urls = list(rows)
    return [Finding(
        "IDX-1", f"{len(urls)} page(s) show a server error message with the server's file paths", Severity.S3,
        Confidence.VERIFIED, Rationale.SELF_EVIDENT.value, ALL_ENGINES, scope_for(urls),
        {"pages": list(rows.values())[:40],
         "rule": "an error marker and a server path, in a 5xx answer, a body under 4 KB, or before the page's <html>"},
        "the live server shows no error details", ERROR_TEXT_FIX,
        notes=["An account folder in a quoted /home/ path is shortened to its first two characters (/home/u8…/)."],
        importance_tier=_tier(urls, key_urls))]


def idx1_http_status(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "HTTP status of crawled URLs"
    data = _index(result)
    key_urls = set(key_page_urls(result, cfg))
    history = attempts_by_url(result)
    inbound = _inlinks(result)
    listed = set(result.sitemap_urls)
    # A CDN's own machinery (Cloudflare's /cdn-cgi/, Akamai's /akam/, Vercel's /_vercel/ ...) is not a page of the site
    # (review H09, G06): a 404 at a bot sensor or the e-mail protection page is what a crawler gets there, not a broken
    # page. IDX-6 says once that Cloudflare's e-mail obfuscation is on.
    machinery = sorted(p.url for p in result.pages if edge_machinery(p.url))
    pages = [p for p in result.pages if p.fetch_class in (FetchClass.OK, FetchClass.ERROR) and p.url not in machinery]
    findings: list[Finding] = []
    observations: list[dict] = []

    persistent_5xx, transport_hard, transport_timeout, single_5xx = [], [], [], []
    # "Every attempt" means every counted fetch of the URL in this audit: the crawl, the IDX-1 refetch, and the
    # PRF rounds (perf_data.attempts_by_url), so IDX-1 and PRF-1/PRF-2 always agree on persistent vs intermittent.
    for page in pages:
        crawl_failed = page.fetch_class == FetchClass.ERROR or (page.status or 0) >= 500
        if not crawl_failed:
            continue
        attempts = [a for a in history.get(page.url, []) if counted(a)]
        if len(attempts) < 2 and page.fetch_class == FetchClass.OK and (page.status or 0) >= 500:
            # A server error seen once and not asked again (the refetch cap): still a finding, said as one observation
            # (review B17), never as a persistent failure.
            single_5xx.append((page, attempts or [{"source": "crawl", "requested_at": page.requested_at,
                                                   "status": page.status, "error": page.error}]))
        elif len(attempts) < 2:
            observations.append({"url": page.url, "metric": "failure not fetched again (refetch cap reached)",
                                 "status": page.status, "error": page.error})
        elif all(failed(a) for a in attempts):
            errors = [a for a in attempts if a["error"]]
            if page.fetch_class == FetchClass.OK and any((a["status"] or 0) >= 500 for a in attempts):
                persistent_5xx.append((page, attempts))
            elif errors and all(a["error"].startswith("timeout") for a in errors) and len(errors) == len(attempts):
                transport_timeout.append((page, attempts))
            else:
                transport_hard.append((page, attempts))
        else:
            observations.append({"url": page.url, "metric": "intermittent failure: succeeded on another attempt "
                                                            "(reported by PRF-1 for timeouts, PRF-2 otherwise)",
                                 "attempts": [{k: a[k] for k in ("source", "status", "error")} for a in attempts]})

    def evidence_rows(pairs):
        return [{"url": p.url, "attempts": [{k: a.get(k) for k in ("source", "requested_at", "status", "error")}
                                            for a in attempts],
                 "reproduce": _curl(p.url, cfg)} for p, attempts in pairs[:40]]

    if persistent_5xx:
        urls = [p.url for p, _ in persistent_5xx]
        findings.append(Finding(
            "IDX-1", f"{len(urls)} URL(s) return a server error (5xx) on every attempt", Severity.S1,
            Confidence.VERIFIED, Rationale.DOCUMENTED.value, ALL_ENGINES, scope_for(urls),
            {"pages": evidence_rows(persistent_5xx), "refetch_delay_s": cfg.refetch_delay_s},
            "pages answer 2xx (or an intentional 3xx/4xx)",
            "Check the server logs for these URLs and fix the error. If a page is gone, return 404/410 or redirect it.",
            importance_tier=_tier(urls, key_urls),
        ))
    if single_5xx:
        urls = [p.url for p, _ in single_5xx]
        findings.append(Finding(
            "IDX-1", f"{len(urls)} URL(s) returned a server error (5xx) on the one request made", Severity.S3,
            Confidence.ESTIMATED, Rationale.DOCUMENTED.value, ALL_ENGINES, scope_for(urls),
            {"pages": evidence_rows(single_5xx), "observation_strength": "single_observation",
             "why_single": "the refetch cap was reached, so the URL was not requested again"},
            "pages answer 2xx (or an intentional 3xx/4xx)",
            "Request these URLs again and check the server logs for the recorded time. If the error repeats, fix it; "
            "if a page is gone, return 404/410 or redirect it.",
            importance_tier=_tier(urls, key_urls),
            notes=["One observation: the URL was not requested again, so whether the error persists is not known."]))
    if transport_hard:
        urls = [p.url for p, _ in transport_hard]
        findings.append(Finding(
            "IDX-1", f"{len(urls)} URL(s) fail at the connection level on every attempt", Severity.S1,
            Confidence.VERIFIED, Rationale.DOCUMENTED.value, ALL_ENGINES, scope_for(urls),
            {"pages": evidence_rows(transport_hard)}, "pages can be fetched",
            "Check DNS, TLS, and the origin server for these URLs; the connection fails before any HTTP response.",
            importance_tier=_tier(urls, key_urls),
        ))
    if transport_timeout:
        urls = [p.url for p, _ in transport_timeout]
        findings.append(Finding(
            "IDX-1", f"{len(urls)} URL(s) time out on every attempt ({cfg.request_timeout_s:g}s limit)", Severity.S1,
            Confidence.INFERRED, Rationale.DOCUMENTED.value, ALL_ENGINES, scope_for(urls),
            {"pages": evidence_rows(transport_timeout), "timeout_s": cfg.request_timeout_s},
            "pages respond well within engine fetch timeouts",
            "Find out why these URLs hang (slow queries, upstream calls, locks) and make them respond quickly.",
            notes=[f"Inferred: assumes answer engines give up within {cfg.request_timeout_s:g} s. Vendors do not "
                   "document their fetch timeouts."],
            importance_tier=_tier(urls, key_urls),
        ))

    referenced_4xx, unreferenced_4xx = [], []
    for page in pages:
        if page.status and 400 <= page.status < 500:
            refs = inbound.get(page.url, [])
            in_sitemap = page.url in listed
            (referenced_4xx if refs or in_sitemap else unreferenced_4xx).append((page, refs, in_sitemap))
    for group, severity, label in ((referenced_4xx, Severity.S2, "linked internally or listed in the sitemap"),
                                   (unreferenced_4xx, Severity.INFO, "not referenced by any crawled page or the sitemap")):
        if not group:
            continue
        urls = [p.url for p, _, _ in group]
        findings.append(Finding(
            "IDX-1", f"{len(urls)} URL(s) return a client error (4xx), {label}", severity, Confidence.VERIFIED,
            Rationale.DOCUMENTED.value, ALL_ENGINES, scope_for(urls),
            {"pages": [{"url": p.url, "status": p.status, "in_sitemap": s, "referenced_by": r[:10],
                        "reproduce": _curl(p.url, cfg)} for p, r, s in group[:40]]},
            "internal links and the sitemap point only at live URLs",
            "Restore the page if it should exist; otherwise remove it from internal links and the sitemap, or "
            "redirect it to its closest replacement.",
            importance_tier=_tier(urls, key_urls),
            notes=(["A redirect pointing at a URL counts as an internal reference."] if severity is Severity.S2 else []),
        ))

    findings += _empty_pages(result, cfg, data, key_urls, observations)
    findings += _error_text(result, cfg, key_urls)

    probe = data.soft_404 or {"sent": False, "reason": "not collected"}
    verdict = soft_404_verdict(probe, result)
    if verdict["soft_404"]:
        answer = (f"redirects ({probe['status']}) to the homepage" if verdict["kind"] == "redirect_to_homepage"
                  else "answers 200, as if the page existed")
        findings.append(Finding(
            "IDX-1", f"A page that does not exist {answer} (soft 404)", Severity.S3, Confidence.VERIFIED,
            "Documented (Google: a missing page should return 404 or 410, not 200 or a redirect to the homepage)",
            INDEX_ENGINES, {"kind": "sitewide", "count": 1, "urls": [result.origin + "/"]},
            {"probe": probe, "reproduce": _curl(probe["url"], cfg)},
            "a missing page answers 404 or 410",
            "Configure the site to return 404 (or 410) for addresses that do not exist, with a helpful error page. "
            "As it is, mistyped and removed URLs look like live pages or like copies of the homepage, so engines "
            "keep them and cannot tell real pages from dead ones.",
            importance_tier=2,
            notes=["One request was made, to a random address generated for this audit. "
                   + probe.get("final_url_note", "")]))
    statuses = defaultdict(int)
    for page in result.pages:
        statuses[str(page.status) if page.status is not None else page.fetch_class.value] += 1
    evidence = {"status_counts": dict(statuses), "refetches": data.refetches,
                "soft_404_probe": {**probe, "verdict": verdict["text"], "assessed": verdict["assessed"]},
                "attempts_counted": "crawl fetch, IDX-1 refetch, and PRF rounds (blocked/rate-limited answers not counted)",
                "excluded": "blocked and rate-limited pages are reported by INT-1, not here",
                "cloudflare_machinery_left_out": {"count": len(machinery), "why": "a CDN's own addresses (Cloudflare's "
                                                  "/cdn-cgi/, Akamai's /akam/, Vercel's /_vercel/ ...) are not pages "
                                                  "of the site", "urls": machinery[:20],
                                                  "vendors": sorted({edge_machinery(u) for u in machinery})}}
    summary = (f"{len(findings)} finding(s) across {len(pages)} fetched URL(s)." if findings
               else f"No 4xx, persistent 5xx, or persistent transport errors across {len(pages)} fetched URL(s).")
    summary += f" Missing-page test: {verdict['text']}."
    for f in findings:
        if 'client error (4xx)' in f.title or 'server error (5xx)' in f.title or 'connection level on every attempt' in f.title or 'time out on every attempt' in f.title:
            f.evidence['retrieval_membership'] = {'urls': list(f.scope.get('_all_urls') or f.scope.get('urls') or []), 'complete': True,
                'basis': 'full URL population classified by this finding before presentation row capping'}
    return CheckResult("IDX-1", title, _status(findings), summary, findings, evidence, observations)


# -- IDX-2 -------------------------------------------------------------------

TEMPORARY_REDIRECTS = (302, 303, 307)
TEMPORARY_FIX = "Make the http:// to https:// redirect permanent (301 or 308) on each hostname."

# DECISIONS 321, made inclusive by DECISIONS 322: a certificate's expiry severity by the days left at the audit: 7 days
# or fewer Blocker, 14 or fewer High, else (inside the warning window, 30 days or fewer) Medium. Once it expires every
# fetch fails, so the nearer it is, the higher.
TLS_EXPIRY_BANDS = ((7, Severity.S1), (14, Severity.S2))


def expiry_severity(days_left: float) -> Severity:
    return next((sev for limit, sev in TLS_EXPIRY_BANDS if days_left <= limit), Severity.S3)


def expiry_finding(not_after: str, entries: list[dict], warning_days: float) -> Finding:
    """One finding per certificate expiry date, for the hosts that share it (also rebuilt offline for a saved audit,
    `reassess_rules._decisions_321`, so the id is the one this engine would give)."""
    days = entries[0]["tls"]["days_left"]
    hosts = ", ".join(e["host"] for e in entries)
    return Finding(
        "IDX-2", f"TLS certificate on {hosts} expires in {days:g} day(s) ({not_after})", expiry_severity(days),
        Confidence.VERIFIED, "Documented (fetch fails once expired)", ALL_ENGINES,
        scope_for([f"https://{e['host']}/" for e in entries], sitewide=True),
        {"hosts": [e["tls"] for e in entries]},
        f"more than {warning_days:g} days of validity left",
        "Renew the certificate now, and check that automatic renewal is working.",
    )


def idx2_tls(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "TLS / HTTPS validity"
    data = _index(result)
    findings: list[Finding] = []
    hosts = data.hosts
    from ..evidence_accuracy import host_assessments
    outcomes = host_assessments(hosts)
    evidence = {"hosts": hosts, "www_variant": data.variant_note or "checked", "host_assessments": outcomes}

    def names(entries):
        return ", ".join(e["host"] for e in entries)

    # Group identical outcomes across the start host and its variant, so one certificate problem is one finding.
    invalid: dict[str, list[dict]] = defaultdict(list)
    expiring: dict[str, list[dict]] = defaultdict(list)
    for entry in hosts:
        tls = entry.get("tls", {})
        if tls.get("valid") is False:
            invalid[tls.get("verify_message") or tls.get("error") or "invalid"].append(entry)
        elif tls.get("valid") and tls.get("days_left") is not None and tls["days_left"] <= cfg.tls_expiry_warning_days:
            expiring[tls["not_after"]].append(entry)

    for message, entries in invalid.items():
        tls = entries[0]["tls"]
        findings.append(Finding(
            "IDX-2", f"TLS certificate is not valid on {names(entries)}: {message}", Severity.S1,
            Confidence.VERIFIED, "Documented (fetch fails)", ALL_ENGINES,
            scope_for([f"https://{e['host']}/" for e in entries], sitewide=True),
            {"hosts": [e["tls"] for e in entries],
             "reproduce": f"openssl s_client -connect {tls['host']}:{tls['port']} -servername {tls['host']} </dev/null"},
            "a valid certificate for every hostname the site answers on, issued by a trusted authority",
            "Reissue the certificate so it covers each of these hostnames (apex and www), and install the full chain. "
            "Every automated fetcher fails on an invalid certificate.",
            notes=(["The www / non-www variant counts as its own entry point: links and typed URLs that use it fail."]
                   if any(e["role"] == "variant" for e in entries) else []),
        ))
    for not_after, entries in expiring.items():
        findings.append(expiry_finding(not_after, entries, cfg.tls_expiry_warning_days))
    # ONE finding for the fact "http:// is not redirected to https://", whatever each host answers (decision 188,
    # which amends 181). Its severity is the highest of its parts: High when the site is reachable, whole, on http://
    # (a host answers 200 there, or redirects to another host's http:// address that does); Low when the request is
    # passed on. Every tested host has its line, the ones that redirect correctly too.
    probed = http_redirect_outcomes(hosts)
    wrong = [row for row in probed if row["outcome"] != "redirects_to_https"]
    if wrong:
        urls = [row.get("http_url") or f"http://{row['host']}/" for row in wrong]
        served = any(row["outcome"] in HTTP_SERVED_OUTCOMES for row in wrong)
        findings.append(Finding(
            "IDX-2", f"No HTTP to HTTPS redirect on {', '.join(row['host'] for row in wrong)}", Severity.S2 if served else Severity.S4,
            Confidence.VERIFIED, "Documented (fetch fails)", ALL_ENGINES, scope_for(urls, sitewide=True),
            {"hosts": probed, "reproduce": f"curl -I {shlex.quote(urls[0])}"},
            "http:// requests redirect (301/308) to the https:// URL",
            "Redirect every http:// URL to its https:// equivalent with a permanent redirect, on each hostname.",
        ))
    # Redirected to https://, but with a temporary redirect (review B12): engines may keep the http:// address as the
    # one they index, since a 302/307 says the move is not for good.
    temporary = [row for row in probed if row["outcome"] == "redirects_to_https" and row.get("status") in TEMPORARY_REDIRECTS]
    if temporary:
        urls = [row.get("http_url") or f"http://{row['host']}/" for row in temporary]
        hsts = hsts_max_age(result)
        # DECISIONS 338: with HSTS of a year or more, browsers go to https:// without asking http:// at all, and Google
        # keeps the https:// address it is sent to in one hop: a temporary code there is hygiene, said as Info.
        long_hsts = hsts is not None and hsts >= HSTS_LONG_S
        findings.append(Finding(
            "IDX-2", f"http:// redirects to https:// with a temporary redirect on {', '.join(row['host'] for row in temporary)}",
            Severity.INFO if long_hsts else Severity.S4, Confidence.VERIFIED,
            "Documented (Google: a permanent redirect for a permanent move)", ALL_ENGINES, scope_for(urls, sitewide=True),
            {"hosts": [{"host": row["host"], "http_url": row.get("http_url"), "status": row.get("status"),
                        "location": row.get("location")} for row in temporary], "reproduce": f"curl -I {shlex.quote(urls[0])}",
             "hsts_max_age_s": hsts},
            "http:// requests redirect (301/308) to the https:// URL", TEMPORARY_FIX,
            notes=[HSTS_NOTE.format(days=round(hsts / 86400))] if long_hsts else []))

    not_assessed = []
    for entry in hosts:
        tls, redirect = entry.get("tls", {}), entry.get("http_redirect", {})
        if tls.get("valid") is None:
            not_assessed.append(f"{entry['host']}: {tls.get('reason') or tls.get('error') or 'TLS not checked'}")
        if not redirect.get("checked"):
            not_assessed.append(f"{entry['host']}: {redirect.get('reason') or 'HTTP to HTTPS redirect not checked'}")
    evidence["not_assessed"] = not_assessed
    if not findings and len(not_assessed) == 2 * len(hosts):
        return CheckResult("IDX-2", title, "not_assessed", "; ".join(not_assessed), evidence=evidence)
    if findings:
        summary = f"{len(findings)} finding(s) across {names(hosts)}."
    else:
        complete = [h for h, o in zip(hosts, outcomes) if o["tls"] == "completed" and o["http_redirect"] == "completed"]
        summary = (f"Certificates valid and http:// redirects to https:// on {names(complete)}." if complete else "No completed host assessment establishes both valid TLS and an HTTP to HTTPS redirect.")
        if len(complete) != len(hosts):
            summary += " Incomplete host assessments: " + "; ".join(not_assessed) + "."
        if data.variant_note:
            summary += f" {data.variant_note}."
    return CheckResult("IDX-2", title, _status(findings), summary, findings, evidence)


# -- IDX-3 -------------------------------------------------------------------

def unfollowed_redirects(result: CrawlResult, redirects: dict[str, str], by_url: dict) -> list[dict]:
    """Redirects whose target is off the audited origin and was therefore never fetched.

    `kind` is "http" when the target is the same host over http:// (the page leaves HTTPS), else "other_host";
    `same_site` tells a subdomain of the audited site from a different site."""
    origin = urlsplit(result.origin)
    rows = []
    for url, target in redirects.items():
        if target in by_url or same_origin(target, result.origin):
            continue
        to = urlsplit(target)
        downgrade = origin.scheme == "https" and to.scheme == "http" and to.hostname == origin.hostname
        rows.append({"url": url, "status": by_url[url].status, "target": target,
                     "kind": "http" if downgrade else "other_host",
                     "same_site": registrable_domain(to.hostname or "") == registrable_domain(origin.hostname or "")})
    return rows


# A redirect that loops only for a visitor who keeps no cookie (DECISIONS 217).
COOKIE_LOOP_FIX = ('Compare the logged cookie-less and cookie-enabled requests. If public access is intended, investigate why their responses differ before changing server configuration.')
COOKIE_LOOP_WHY = ("Maya observed different outcomes with and without the site's cookie. Other clients and real search or AI crawlers were not tested.")


def idx3_redirects(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Redirect chains and loops"
    key_urls = set(key_page_urls(result, cfg))
    by_url = {p.url: p for p in result.pages}
    redirects = crawl_redirects(result)
    walks, loops = redirect_walks(redirects)
    chains = []
    for hops in walks:
        if len(hops) - 1 >= 2:
            final = by_url.get(hops[-1])
            chains.append({"hops": hops, "redirects": len(hops) - 1,
                           "final_status": final.status if final else None,
                           "final_fetched": final is not None})

    # One response is not enough to say a URL persistently cycles (DECISIONS 195): each loop, and the homepage, was walked
    # again after the crawl (index_data.recheck_redirects). Persistence also requires the cookie walk. One walk ends
    # on the page: the redirect is intermittent. No re-check could be made: said as seen once, never as a blocker.
    index = getattr(result, "index", None)
    rechecks = dict(getattr(index, "redirect_rechecks", None) or {})
    wanted = cfg.redirect_recheck_attempts
    sorted_loops: dict[str, list[list[str]]] = {"always": [], "cookie": [], "intermittent": [], "unchecked": []}
    for loop in loops:
        sorted_loops[redirect_verdict(rechecks.get(loop[0]), wanted)].append(loop)
    # The homepage answered in the crawl and redirected to itself on a re-check: the same intermittent redirect.
    seen_later = [entry for entry in rechecks.values() if entry.get("why") == "homepage" and entry["url"] not in redirects
                  and any(a.get("outcome") == LOOPS for a in entry.get("attempts") or [])]

    def walk_of(a: dict) -> dict:
        return {"outcome": a.get("outcome"), "reason": a.get("reason"), "final_status": a.get("final_status"),
                "client": "Maya native crawler", "cycle_observed": a.get("cycle_observed"),
                "readable_html": a.get("readable_html"), "fetch_class": a.get("fetch_class"),
                "hops": [{"requested_at": h.get("requested_at"), "error": h.get("error"), "url": h.get("url"), "status": h.get("status"), "location": h.get("location"),
                          "set_cookie": bool(h.get("set_cookie")), **({"cookie_sent": h["cookie_sent"]} if "cookie_sent" in h else {})}
                         for h in a.get("hops") or []]}

    def attempts_of(urls: list[str]) -> dict[str, list[dict]]:
        return {url: [walk_of(a) for a in rechecks[url].get("attempts") or []] for url in urls if url in rechecks}

    def cookie_walks_of(urls: list[str]) -> dict[str, dict]:
        # Whether a cookie was set and sent back, never its value (DECISIONS 217).
        return {url: walk_of(rechecks[url]["cookie_walk"]) for url in urls if (rechecks.get(url) or {}).get("cookie_walk")}

    findings: list[Finding] = []
    if sorted_loops["always"]:
        always = sorted_loops["always"]
        urls = sorted({hop for loop in always for hop in loop[:-1]})
        findings.append(Finding(
            "IDX-3", f"{len(always)} redirect loop(s) observed in the tested native client", Severity.S1, Confidence.VERIFIED,
            "Documented (loops)", ALL_ENGINES, scope_for(urls),
            {"loops": always, "rechecks": attempts_of([loop[0] for loop in always]), "attempts_per_url": 1 + wanted,
             "cookie_walks": cookie_walks_of([loop[0] for loop in always]),
             "reproduce": _curl(always[0][0], cfg)},
            "every redirect ends at a page", 'Inspect the server request logs for these times and client, identify the cause of the observed cycle, then retest with and without cookies.',
            importance_tier=_tier(urls, key_urls),
            notes=[f"Verified: the URL looped in the crawl and on each of {wanted} further request(s) made after it."],
        ))
    if sorted_loops["cookie"]:
        # Every cookie-less request looped; the walk that sent back the site's own cookie loaded the page (DECISIONS 217).
        loops_c = sorted_loops["cookie"]
        urls = sorted({hop for loop in loops_c for hop in loop[:-1]})
        findings.append(Finding(
            "IDX-3", f"{len(urls)} URL(s) loop in Maya's cookie-less checks; with the cookie the site sets, "
                     "the page loads", Severity.S3, Confidence.VERIFIED, Rationale.SELF_EVIDENT.value, ALL_ENGINES,
            scope_for(urls),
            {"urls": urls, "loops": loops_c, "rechecks": attempts_of([loop[0] for loop in loops_c]),
             "cookie_walks": cookie_walks_of([loop[0] for loop in loops_c]), "attempts_per_url": 1 + wanted,
             "cookie_values_kept": False,
             "reproduce": _curl(urls[0], cfg)},
            "every redirect ends at a page", COOKIE_LOOP_FIX, importance_tier=_tier(urls, key_urls),
            notes=[COOKIE_LOOP_WHY,
                   f"Verified: the URL looped in the crawl and on each of {wanted} further request(s) made after it."]))
    if sorted_loops["intermittent"] or seen_later:
        some = sorted_loops["intermittent"]
        urls = sorted({hop for loop in some for hop in loop[:-1]} | {entry["url"] for entry in seen_later})
        findings.append(Finding(
            "IDX-3", f"{len(urls)} URL(s) intermittently redirect to themselves; the page loads on another try", Severity.S3,
            Confidence.VERIFIED, "Self-evident harm (a request that is sent in a circle is a wasted request)", ALL_ENGINES,
            scope_for(urls),
            {"urls": urls, "loops_in_the_crawl": some,
             "native_success_in_crawl": [{"url": p.url, "requested_at": p.requested_at, "status": p.status,
                                          "readable_html": True}
                                         for p in result.pages if p.url in urls and _readable_html(p)],
             "rechecks": attempts_of([loop[0] for loop in some] + [entry["url"] for entry in seen_later]),
             "reproduce": _curl(urls[0], cfg)},
            "a URL answers the same way on every request",
            'Compare the successful and cyclic requests at the recorded times. Identify the cause before changing configuration; then repeat the same client checks.',
            importance_tier=_tier(urls, key_urls),
            notes=["Verified: on at least one request the URL redirected back to itself, and on at least one other it "
                   "answered with the page. How often it happens is not measured: a few requests are not a rate."],
        ))
    if sorted_loops["unchecked"]:
        once = sorted_loops["unchecked"]
        urls = sorted({hop for loop in once for hop in loop[:-1]})
        why = sorted({str(rechecks[loop[0]].get("reason") or next((a.get("reason") for a in rechecks[loop[0]].get("attempts") or [] if a.get("reason")), None)
                          or "the re-checks did not all give an answer") if loop[0] in rechecks
                      else "no further request was made to this URL (the page was not read by Maya's own crawler, or the loop is beyond the re-check cap)"
                      for loop in once})
        findings.append(Finding(
            "IDX-3", f"{len(urls)} URL(s) have observed redirect cycles; verification is incomplete", Severity.S3,
            Confidence.INFERRED, "Documented (loops)", ALL_ENGINES, scope_for(urls),
            {"loops": once, "rechecks": attempts_of([loop[0] for loop in once]), "not_rechecked_because": why, "cookie_walks": cookie_walks_of([loop[0] for loop in once]),
             "reproduce": _curl(once[0][0], cfg)},
            "every redirect ends at a page",
            'Complete the missing native and cookie-enabled checks. Compare request logs before selecting a remedy; the available observations do not establish persistence.',
            importance_tier=_tier(urls, key_urls),
            notes=['The native crawl observed a cycle. Persistence is unknown because the required repeated and cookie-enabled verification did not complete. This is not reported as a blocker.'],
        ))
    if chains:
        heads = [c["hops"][0] for c in chains]
        findings.append(Finding(
            "IDX-3", f"{len(chains)} redirect chain(s) of 2 or more hops", Severity.S4, Confidence.VERIFIED,
            "Hypothesis (latency effect of chains)", ALL_ENGINES, scope_for(heads),
            {"chains": sorted(chains, key=lambda c: -c["redirects"]),
             "reproduce": f"curl -sIL {shlex.quote(heads[0])}"},
            "at most one redirect before the final page",
            "Point the first URL, and any internal links to it, straight at the final destination.",
            importance_tier=_tier(heads, key_urls),
            notes=["Capped at S4: the harm from a chain rests on added latency, which is a Hypothesis."],
        ))

    # A redirect that leaves the audited origin is not followed (the crawl stays on one scheme and host), so
    # the page a visitor ends on was never checked. Say so, with the target, instead of leaving a silent gap.
    unfollowed = unfollowed_redirects(result, redirects, by_url)
    for kind, severity, rationale, what, fix in (
            ("http", Severity.S3, "Documented (HTTPS as the secure, preferred version of a page)",
             "redirect from https:// to an http:// address",
             "Redirect to the https:// address. If the http:// address then redirects back to https://, remove the detour."),
            ("other_host", Severity.INFO, Rationale.SELF_EVIDENT.value, "redirect to another host",
             "Nothing to fix if the move is intended. To have the destination checked, audit that host as well.")):
        rows = [row for row in unfollowed if row["kind"] == kind]
        if not rows:
            continue
        urls = [row["url"] for row in rows]
        findings.append(Finding(
            "IDX-3", f"{len(rows)} page(s) {what}, which this audit did not follow", severity, Confidence.VERIFIED,
            rationale, ALL_ENGINES, scope_for(urls),
            {"redirects": rows[:80], "count": len(rows), "reproduce": f"curl -sI {shlex.quote(urls[0])}"},
            "a redirect ends at a page on the audited https:// site" if kind == "http" else
            "the destination of every redirect is known", fix, importance_tier=_tier(urls, key_urls),
            notes=["The redirect and its target are Verified. The target was not fetched: the audit stays on "
                   f"{result.origin}, so nothing is known about the page a visitor ends on."]))

    links_to_redirects = [{"source": p.url, "target": e["target"], "anchor": e["anchor"]}
                          for p in result.pages for e in p.outlinks if e["target"] in redirects]
    observations = ([{"metric": "internal links pointing at redirecting URLs", "value": len(links_to_redirects),
                      "sample": links_to_redirects[:20]}] if links_to_redirects else [])
    summary = (f"{len(findings)} finding(s) among {len(redirects)} redirecting URL(s)." if findings
               else f"{len(redirects)} redirecting URL(s); no loops and no chains of 2+ hops.")
    return CheckResult("IDX-3", title, _status(findings), summary, findings,
                       {"redirecting_urls": len(redirects), "redirects_not_followed": len(unfollowed),
                        "loops_rechecked": {kind: len(found) for kind, found in sorted_loops.items()},
                        "homepage_rechecks": next(([a.get("outcome") for a in entry.get("attempts") or []]
                                                   for entry in rechecks.values() if entry.get("why") == "homepage"), None),
                        "recheck_requests": sum(len(a.get("hops") or []) for entry in rechecks.values() for a in entry.get("attempts") or []),
                        "cookie_recheck_requests": sum(len((entry.get("cookie_walk") or {}).get("hops") or []) for entry in rechecks.values())},
                       observations)


# -- IDX-4 -------------------------------------------------------------------

def _resolve_target(target: str, result: CrawlResult, data: IndexData) -> tuple[dict | None, list[str]]:
    """Follow a canonical target through crawled or fetched redirects to its final observation."""
    by_url = {p.url: p for p in result.pages}
    hops = [target]
    for _ in range(6):
        page = by_url.get(target)
        if page is not None:
            obs = {"url": page.url, "status": page.status, "error": page.error, "fetch_class": page.fetch_class.value,
                   "analysis": page.analysis, "noindex": noindex_directives(page.analysis, page.headers),
                   "location": page.redirect_location}
        else:
            obs = data.canonical_targets.get(target)
        if obs is None or obs.get("skipped"):
            return obs, hops
        if obs["status"] and 300 <= obs["status"] < 400 and obs.get("location"):
            target = obs["location"]
            hops.append(target)
            continue
        return obs, hops
    return None, hops


CANONICAL_REDIRECT_DOC = ("Documented (Google: rel=canonical should name the preferred, final URL; a redirecting "
                          "target is a mixed signal)")
VARIANT_CANONICAL_FIX = "Write the canonical with the address the page is served at: its https:// scheme and its own host."
TWIN_SERVED_FIX = ("Redirect every address on {old} to the same address on {new} with a permanent redirect (at the server, "
                   "the CDN or the platform's domain setting), so each page answers at one address only.")


def twin_served(host_moves: list | None, pages: list) -> list[dict]:
    """DECISIONS 359: the pages the site's earlier address answered with their content instead of redirecting to the
    address the crawl moved to (`crawl.host_moves[].copies`), and the start page when it was one of them. `pages`: page
    records (PageFetch or saved dicts) for the start page's answer."""
    rows = []
    for move in host_moves or []:
        if not isinstance(move, dict):
            continue
        old = str(move.get("from") or "")
        for p in pages:
            get = (lambda k, p=p: p.get(k)) if isinstance(p, dict) else (lambda k, p=p: getattr(p, k, None))
            status = get("status")
            if (get("discovered_via") == "start" and isinstance(status, int) and 200 <= status < 300
                    and (get("url") or "").startswith(old + "/")):
                canon = next(iter(((get("analysis") or {}).get("canonicals") or [])), None)
                if canon and same_origin(canon, str(move.get("to") or "")):
                    rows.append({"url": get("url"), "status": status, "canonical": canon, "from": old, "to": move.get("to")})
        rows += [{**c, "from": old, "to": move.get("to")} for c in move.get("copies") or [] if isinstance(c, dict)]
    return rows
MIXED_SIGNALS_FIX = ("Keep the canonical and remove noindex to fold the page into its target, or keep noindex and make "
                     "the page self-canonical.")


def idx4_canonicals(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Canonical signals"
    data = _index(result)
    key_urls = set(key_page_urls(result, cfg))
    pages = [p for p in result.pages if _readable_html(p) and p.content_checks_eligible]
    conflicts, broken, different, same, cross_origin, unassessed = [], [], [], [], [], []
    # Review B02 / B03: a canonical on the site's own http:// or www variant, noindex beside a canonical elsewhere, a
    # canonical written as a relative address, and indexable pages that declare none.
    variant, mixed, relative, without = [], [], [], []
    listing_views = []  # review G01: parameter or pagination views canonical to their list
    redirecting, loops = [], []  # DECISIONS 263: a canonical that names an address which redirects
    # DECISIONS 278: a canonical printed after a body element that ended <head> early is not read (DECISIONS 260); the
    # page is not "without a canonical", its canonical could not be judged.
    after_head = []

    for page in pages:
        chosen, html, header = effective_canonical(page)
        declared = sorted(set(html) | set(header))
        noindex = noindex_directives(page.analysis, page.headers)
        written = [h.strip() for h in (page.analysis.get("canonicals") or []) if h and h.strip()]
        loose = [h for h in written if not urlsplit(h).scheme and not h.startswith("//")]
        if loose:
            relative.append({"url": page.url, "written": loose[:3]})
        if not declared:
            if (page.analysis.get("outside_head") or {}).get("canonical"):
                after_head.append(page.url)
            elif not noindex:
                without.append(page.url)
            continue
        if len(declared) > 1:
            conflicts.append({"url": page.url, "html": html, "header": header})
            # Google ignores every canonical when they disagree, so none of them is judged as the chosen one.
            unassessed.append({"url": page.url, "canonical": declared,
                               "reason": "the page declares more than one canonical, so no target is judged"})
            continue
        found = canonical_variant(chosen, page.url)
        target = found["counterpart"] if found else chosen
        # A canonical that only upgrades an http:// page to its https:// address names the better address: not reported.
        upgrade = found is not None and found["differs_in"] == "scheme" and urlsplit(chosen).scheme == "https"
        if found and not upgrade:
            variant.append({"url": page.url, "canonical": chosen, "differs_in": found["differs_in"], "judged_as": target})
        if target == page.url:
            continue
        if noindex:
            mixed.append({"url": page.url, "canonical": chosen, "noindex": noindex})
        if not same_origin(target, page.url):
            cross_origin.append({"url": page.url, "canonical": chosen})
            continue
        final, hops = _resolve_target(target, result, data)
        row = {"url": page.url, "canonical": chosen, "resolved_via": hops}
        if len(hops) > 1:
            landed = normalize_url(hops[-1], page.url) or hops[-1]
            if landed == page.url:
                # The canonical leaves the page and the redirect brings it back: neither address is stated as the
                # preferred one (seen live on a homepage whose canonical /tr/tr/ redirects to /).
                loops.append({**row, "redirects_to": landed})
                continue
            redirecting.append({**row, "redirects_to": landed})
        if final is None or final.get("skipped"):
            unassessed.append({**row, "reason": (final or {}).get("skipped", "canonical target not fetched (cap)")})
        elif final["error"] or (final["status"] and final["status"] >= 400):
            broken.append({**row, "target_status": final["status"], "target_error": final["error"]})
        elif final["noindex"]:
            broken.append({**row, "target_status": final["status"], "target_noindex": final["noindex"]})
        elif final["analysis"] is None:
            unassessed.append({**row, "reason": "canonical target is not a readable HTML page"})
        elif view := listing_view_of(page.url, target):
            # A filtered, sorted or paged view of a list naming the list as canonical (review G01): ordinary
            # consolidation. Its rows differ from page 1 by design, so the content is not compared.
            listing_views.append({**row, "view": view})
        else:
            verdict = compare_content(page.analysis, final["analysis"], cfg.same_content_block_share,
                                      cfg.same_content_similarity)
            row = {**row, "comparison": verdict["basis"], "value": verdict["value"],
                   "confidence": verdict["confidence"], "differing_blocks": verdict["differing_blocks"]}
            if verdict["same"] is None:
                unassessed.append({**row, "reason": "neither page has text to compare"})
            elif verdict["same"]:
                same.append(row)
            else:
                different.append(row)

    findings: list[Finding] = []
    if broken:
        urls = [r["url"] for r in broken]
        findings.append(Finding(
            "IDX-4", f"{len(urls)} page(s) declare a canonical that is broken, noindexed, or an error", Severity.S2,
            Confidence.VERIFIED, "Documented (Google, Bing) / Hypothesis (others)", INDEX_ENGINES, scope_for(urls),
            {"pages": broken[:40]}, "canonicals point at live, indexable pages",
            "Point the canonical at the live, indexable URL (usually the page itself).",
            importance_tier=_tier(urls, key_urls),
        ))
    if loops:
        urls = [r["url"] for r in loops]
        findings.append(Finding(
            "IDX-4", f"{len(urls)} page(s) declare a canonical that redirects back to the page itself", Severity.S2,
            Confidence.VERIFIED, CANONICAL_REDIRECT_DOC, INDEX_ENGINES, scope_for(urls), {"pages": loops[:40]},
            "the canonical names the page's own final address", "Make the canonical the page's own address (the one "
            "the redirect ends at); fix the template that writes the other address.", importance_tier=_tier(urls, key_urls)))
    if redirecting:
        urls = [r["url"] for r in redirecting]
        findings.append(Finding(
            "IDX-4", f"{len(urls)} page(s) declare a canonical that redirects to another address", Severity.S3,
            Confidence.VERIFIED, CANONICAL_REDIRECT_DOC, INDEX_ENGINES, scope_for(urls), {"pages": redirecting[:40]},
            "the canonical names the final address, not one that redirects",
            "Write the address the redirect ends at as the canonical.", importance_tier=_tier(urls, key_urls),
            notes=["The content of the address the redirect ends at is still compared below (same or different)."]))
    copies = twin_served(getattr(result, "host_moves", None), result.pages)
    served = {r["url"] for r in copies}
    variant = [r for r in variant if r["url"] not in served]  # DECISIONS 359: said once, by the card below
    if variant:
        urls = [r["url"] for r in variant]
        findings.append(Finding(
            "IDX-4", f"{len(urls)} page(s) declare a canonical on the http:// or www variant of this site", Severity.S3,
            Confidence.VERIFIED, "Documented (Google, Bing: the canonical names the preferred address)", INDEX_ENGINES,
            scope_for(urls), {"pages": variant[:40]},
            "the canonical uses the address the page is served at: its own scheme and host", VARIANT_CANONICAL_FIX,
            importance_tier=_tier(urls, key_urls),
            notes=["Each canonical was judged as the same address on the audited scheme and host (`judged_as`); a page "
                   "whose canonical is its own address on the variant counts as self-canonical in every other check."]))
    if copies:  # DECISIONS 359: the site's other address serves pages itself instead of redirecting: one card
        urls = [r["url"] for r in copies]
        old_host, new_host = urlsplit(copies[0]["from"]).hostname, urlsplit(str(copies[0]["to"])).hostname
        findings.append(Finding(
            "IDX-4", f"{len(urls)} page(s) on {old_host} answer with their content instead of redirecting to {new_host}",
            Severity.S3, Confidence.VERIFIED, "Documented (Google: one address per page; redirect duplicates)", INDEX_ENGINES,
            scope_for(urls), {"pages": copies[:40], "from": copies[0]["from"], "to": copies[0]["to"]},
            f"every address on {old_host} redirects permanently to the same address on {new_host}",
            TWIN_SERVED_FIX.format(old=old_host, new=new_host), importance_tier=_tier(urls, key_urls),
            notes=["Most addresses on this host redirect; these answered with the page instead, so the same page has two "
                   "addresses. Each was read once, at the address the crawl moved to."]))
    if mixed:
        urls = [r["url"] for r in mixed]
        findings.append(Finding(
            "IDX-4", f"{len(urls)} page(s) are noindex and declare a canonical to another URL", Severity.S3,
            Confidence.VERIFIED, "Documented (Google: noindex beside rel=canonical sends mixed signals)", INDEX_ENGINES,
            scope_for(urls), {"pages": mixed[:40]}, "either a canonical to another URL or noindex, not both",
            MIXED_SIGNALS_FIX, importance_tier=_tier(urls, key_urls)))
    if conflicts:
        urls = [r["url"] for r in conflicts]
        findings.append(Finding(
            "IDX-4", f"{len(urls)} page(s) declare conflicting canonicals", Severity.S3, Confidence.VERIFIED,
            "Documented (Google, Bing) / Hypothesis (others)", INDEX_ENGINES, scope_for(urls),
            {"pages": conflicts[:40]}, "one canonical, declared in one place",
            "Keep a single canonical declaration (HTML or HTTP header) and remove or align the others.",
            notes=["Several differing <link rel=canonical> tags on one page are treated as conflicting too."],
            importance_tier=_tier(urls, key_urls),
        ))

    def canon_build(rows, severity_label):
        by_url = {r["url"]: r for r in rows}

        def build(its, severity, intent):
            urls = [u for u, _ in its]
            chosen_rows = [by_url[u] for u in urls]
            different_content = severity_label == "different"
            return Finding(
                "IDX-4",
                (f"{len(urls)} page(s) are canonicalized to a URL with different content" if different_content
                 else f"{len(urls)} page(s) are canonicalized to a URL with the same content"),
                severity, Confidence.ESTIMATED if different_content or any(r["confidence"] == "estimated" for r in chosen_rows)
                else Confidence.VERIFIED,
                "Documented (Google, Bing) / Hypothesis (others)", INDEX_ENGINES, scope_for(urls),
                {"pages": chosen_rows[:40], "same_content_block_share": cfg.same_content_block_share,
                 "same_content_sketch_threshold": cfg.same_content_similarity},
                "a page whose own content should be cited is self-canonical",
                ("Engines that honor the canonical will index the target instead of this page's own content. Make "
                 "the page self-canonical if its content should be cited, or mark it as intended." if different_content
                 else "Normal consolidation; no action needed if intended."),
                intent=intent, importance_tier=_tier(urls, key_urls),
                notes=(["Inferred: Google documents rel=canonical as a hint, so the engine may choose differently "
                        "(Search Console, IDX-9, can confirm for Google).",
                        "Same-content thresholds are policy: the word share (0.8) is set from one measured site, "
                        "the sketch threshold (0.9, used only without the page text) is a round number (LG-21). The "
                        "passages that differ are quoted per page."] if different_content else []),
            )
        return build

    if different:
        items = [(r["url"], None) for r in different]
        findings += _with_intent("IDX-4", "canonicalized", items, Severity.S2, key_urls, cfg, canon_build(different, "different"))
    for confidence in ("verified", "estimated"):
        rows = [r for r in same if r["confidence"] == confidence]
        if rows:
            items = [(r["url"], None) for r in rows]
            findings += _with_intent("IDX-4", "canonicalized", items, Severity.INFO, key_urls, cfg, canon_build(rows, "same"))

    review_items = []
    if cross_origin:
        urls = [r["url"] for r in cross_origin]
        review_items.append(ReviewItem(
            "IDX-4", f"{len(urls)} page(s) declare a canonical on another site",
            "Engines that honor the canonical will credit the other site for this content. That is correct for "
            "syndicated copies and wrong otherwise; content on another origin is not fetched, so it was not compared.",
            Confidence.VERIFIED, INDEX_ENGINES, scope_for(urls), {"pages": cross_origin[:40]},
            "Confirm each canonical is intended. If this site is the original source, make the pages self-canonical.",
            importance_tier=_tier(urls, key_urls),
        ))
    evidence = {"pages_checked": len(pages), "not_assessed": unassessed, "not_assessed_count": len(unassessed),
                "canonical_after_head": after_head[:40], "canonical_after_head_count": len(after_head)}
    # Observations, not findings: Google does not require a canonical, and resolves a relative one against the page.
    observations = []
    if relative:
        observations.append({"metric": "canonical written as a relative address (Google asks for an absolute one)",
                             "value": len(relative), "sample": relative[:20]})
    if listing_views:
        observations.append({"metric": "parameter or pagination pages consolidate to their listing (a filter, sort or "
                                       "page-2 view names the list as canonical: normal, no action)",
                             "value": len(listing_views), "sample": listing_views[:20]})
    if without:
        observations.append({"metric": "indexable pages that declare no canonical (optional; a self-canonical makes "
                                       "the preferred address explicit)", "value": len(without), "sample": without[:20]})
    summary = (f"{len(findings)} finding(s), {len(review_items)} review item(s) across {len(pages)} page(s)."
               if findings or review_items else
               f"No canonical problem on {len(pages) - len(unassessed)} of {len(pages)} readable page(s)."
               + (f" {len(unassessed)} canonical target(s) could not be judged." if unassessed else ""))
    return CheckResult("IDX-4", title, _status(findings, review_items), summary, findings, evidence, observations, review_items)


# -- IDX-5 -------------------------------------------------------------------

def _parse_lastmod(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _redirect_end(location: str | None, by_url: dict) -> tuple[str, int] | None:
    """Where a redirect ends, from the crawl's own records: (url, status), or None when the crawl did not follow it."""
    seen = set()
    while location and location not in seen and len(seen) < 6:
        seen.add(location)
        page = by_url.get(location)
        if page is None or not page.status:
            return None
        if not 300 <= page.status < 400:
            return location, page.status
        location = page.redirect_location
    return None


def sitemap_judgments(result: CrawlResult, cfg: CrawlConfig) -> dict:
    """Every sitemap URL, judged from the crawl or from the sitemap check's light request (DECISIONS 206):
    {"checked": [url], "not_live": [{"url", "kind", "status", ...}], "canonical_elsewhere": [...], "disallowed": [url],
    "not_checked": [url], "why_not_checked": "...", "summary": {...}}. A file (a nested sitemap, an image, a PDF) is
    not a page and is left out."""
    data = getattr(result, "index", None)
    check = getattr(data, "sitemap_check", None)
    by_url = {p.url: p for p in result.pages}
    light = {row["url"]: row for row in (check.rows if check is not None else [])}
    disallowed = set(check.disallowed) if check is not None else set()
    out = {"checked": [], "not_live": [], "canonical_elsewhere": [], "disallowed": [], "not_checked": []}
    by_crawl = by_light = files = 0
    kinds_unknown: dict[str, int] = {}
    for url in result.sitemap_urls:
        if non_page_kind(url):
            files += 1
            continue
        page, row = by_url.get(url), light.get(url)
        if page is not None:
            kind, source = page_kind(page), "crawl"
            facts = {"status": page.status, "error": page.error, "location": page.redirect_location,
                     "noindex": noindex_directives(page.analysis, page.headers) if page.analysis else []}
        elif row is not None:
            kind, source = row_kind(row), "light request"
            facts = {k: row.get(k) for k in ("status", "error", "location", "noindex", "requested_at", "bytes")}
        elif url in disallowed:
            out["disallowed"].append(url)
            continue
        else:
            out["not_checked"].append(url)
            continue
        if kind in ("blocked", "no_answer"):
            out["not_checked"].append(url)
            kinds_unknown[kind] = kinds_unknown.get(kind, 0) + 1
            continue
        if kind == "redirect" and (ends := _redirect_end(facts.get("location"), by_url)) and 400 <= ends[1] < 500:
            # DECISIONS 278: a listed URL that redirects to a page the crawl saw answer 4xx is not found, not "a redirect".
            kind, facts = "not_found", {**facts, "redirects_to_error": {"url": ends[0], "status": ends[1]}}
        out["checked"].append(url)
        by_crawl, by_light = by_crawl + (source == "crawl"), by_light + (source == "light request")
        if kind in NOT_LIVE_KINDS:
            out["not_live"].append({"url": url, "kind": kind, "source": source, **facts})
        elif kind == "canonical_elsewhere":
            canonical = effective_canonical(page)[0] if page is not None else row.get("canonical")
            out["canonical_elsewhere"].append({"url": url, "canonical": canonical})
    reasons = dict((check.not_checked if check is not None else {}) or {})
    for kind, n in kinds_unknown.items():
        reasons[{"blocked": "blocked_answer", "no_answer": "no_answer"}[kind]] = n
    if check is None and out["not_checked"]:
        reasons["not_collected"] = len(out["not_checked"])
    words = {"cap": "the cap of light requests", "rate_limit": "the site answered 429", "blocked": "the site blocked the requests",
             "time_limit": "the time limit", "off": "the sitemap check is off", "single_page": "a single-page audit",
             "crawl_stopped": "the crawl stopped early", "robots_unreadable": "robots.txt could not be read",
             "blocked_answer": "blocked or challenged answers", "no_answer": "no answer", "not_collected": "not collected"}
    out["why_not_checked"] = ", ".join(words.get(k, k) for k in reasons) or "not collected"
    out["summary"] = {"listed": len(result.sitemap_urls), "files_left_out": files, "checked": len(out["checked"]),
                      "checked_by_crawl": by_crawl, "checked_by_light_request": by_light,
                      "disallowed": len(out["disallowed"]), "not_checked": len(out["not_checked"]),
                      "not_checked_because": reasons, "sampled": bool(check is not None and check.sampled),
                      "sample_files": getattr(check, "sample_files", 0) if check is not None else 0,
                      "wanted": check.wanted if check is not None else None,
                      "cap": check.cap if check is not None else None,
                      "stopped_because": check.stopped_because if check is not None else None,
                      "not_checked_sample": (check.not_checked_sample if check is not None else [])[:20],
                      "light_request": "one GET each, at most 64 KB read, no redirect followed"}
    return out


SHARE_FIX = "Remove redirected, broken, empty and noindexed URLs from the sitemap, or fix the pages."
DRAFT_FIX = "Add noindex to these pages or remove them, and take them out of the sitemap."
# What root_cause and IDX-7 read to say a draft page once (review H13).
DRAFT_TITLE = re.compile(r"draft or test page\(s\) are indexable and listed in the sitemap")


def _draft_pages(result: CrawlResult, key_urls: set[str]) -> list[Finding]:
    """Pages left published from a draft or a test, listed in the sitemap and open to indexing (review H13). Said once
    here: IDX-7 does not call them orphans, IDX-8 does not call them copies, and STR-1's missing titles leave them out
    (maya_audit.root_cause)."""
    rows = draft_pages(result)
    if not rows:
        return []
    urls = [row["url"] for row in rows]
    return [Finding(
        "IDX-5", f"{len(urls)} draft or test page(s) are indexable and listed in the sitemap", Severity.S3,
        Confidence.INFERRED, "Self-evident harm (a draft page is offered to engines as a page of the site)", INDEX_ENGINES,
        scope_for(urls), {"pages": rows[:40], "draft_urls": urls,
                          "rule": "a word such as test, deneme, draft, taslak, ornek, sample or demo in the address, or "
                                  "another page's address with a number after it; with no title or found only through the sitemap"},
        "the sitemap lists only finished pages meant to be found", DRAFT_FIX, importance_tier=_tier(urls, key_urls),
        notes=["Verified: each page answers 200, has no noindex and is listed in the sitemap. Inferred: that it is a draft "
               "or a test, from the signals listed for each page.",
               "These pages are said here only: not as orphans (IDX-7), copies (IDX-8) or pages without a title (STR-1)."])]
# The share's title when some of its URLs are IDX-1's empty or failing pages (maya_audit.root_cause, DECISIONS 215). Its
# first number is the URLs left in the finding, the same number its scope gives (review CR-28); the share, counted with
# IDX-1's pages as DECISIONS 215 keeps it, is said after them.
IDX1_BESIDE = ("{rest} of {assessed} sitemap URL(s){checked} are not live, indexable pages besides the {same} empty or failing "
               "page(s) reported under IDX-1 ({share} with them){tail}")
SHARE_TITLE = re.compile(r"^(?P<bad>\d+) of (?P<assessed>\d+) sitemap URL\(s\)(?P<checked> checked)? \((?P<share>\d+%)\) "
                         r"are not live, indexable pages(?P<tail>.*)$")
FAILED_FILE_FIX = "Remove the file from the sitemap index (or robots.txt), or publish it again."
_MAYA_LIMITS = ("larger than", "decompressed sitemap larger", "audit_deadline_skipped")


def _failed_sitemap_files(result: CrawlResult) -> list[Finding]:
    """A sitemap file named in robots.txt or a sitemap index that answered 4xx or 5xx, did not arrive, or could not be
    read as a sitemap (DECISIONS 206). The /sitemap.xml Maya asks for without its being named is never reported. A
    redirect off the site and a file over Maya's own size limit are not reported either (agent defaults)."""
    named = getattr(result, "_sitemap_named_in", None) or {}
    rows = []
    for doc in result.sitemap_docs:
        where = named.get(doc.url)
        if not where or where == SITEMAP_GUESSED:
            continue
        error = doc.error or ""
        if error.startswith(_MAYA_LIMITS) or (doc.status is not None and 300 <= doc.status < 400):
            continue
        failed = (doc.status is not None and doc.status >= 400) or (doc.status is None and error) or \
            (doc.status is not None and 200 <= doc.status < 300 and (error or doc.kind is None))
        if failed:
            rows.append({"url": doc.url, "named_in": where, "status": doc.status, "error": doc.error or None,
                         "reproduce": f"curl -i {shlex.quote(doc.url)}"})
    if not rows:
        return []
    return [Finding(
        "IDX-5", f"{len(rows)} sitemap file(s) named in the sitemap index or robots.txt could not be loaded",
        Severity.S3, Confidence.VERIFIED, "Documented (Google/Bing use sitemaps)", INDEX_ENGINES,
        scope_for([r["url"] for r in rows], sitewide=True), {"files": rows[:40]},
        "every sitemap file that is named can be loaded", FAILED_FILE_FIX)]


MALFORMED_FIX = ("Write the sitemap in UTF-8 and percent-encode each address (ö is written %C3%B6, a space %20), or let "
                 "the site's sitemap tool build it again.")
NOT_ENCODED_FIX = ("Percent-encode the letters outside A to Z in each sitemap address (ö is written %C3%B6). Most crawlers "
                   "read both forms; the encoded one is the standard.")
MALFORMED_GENERAL = ("A “?” stands where a letter should be, often a Turkish letter such as ö or ş; the sitemap is probably "
                     "not written in UTF-8.")


def _malformed_sitemap_urls(result: CrawlResult) -> list[Finding]:
    """Separate demonstrable invalid characters from uncertain query intent; no destination is requested here."""
    findings: list[Finding] = []
    wrong = [(url, malformed(url)) for url in result.sitemap_urls]
    wrong = [(url, why) for url, why in wrong if why]
    for suspected in (False, True):
        selected = [(url, why) for url, why in wrong if (why == 'question_mark') == suspected]
        if not selected:
            continue
        urls = [url for url, _ in selected]
        rows = [{'url': url, 'why': 'valid query syntax; intended path not established' if suspected else
                 'unescaped space' if why == 'space' else 'replacement character or invalid percent escape'} for url, why in selected]
        findings.append(Finding(
            'IDX-5', (f'{len(urls)} sitemap URL(s) use word-like queries; intended paths are unassessed' if suspected else
                      f'{len(urls)} sitemap URL(s) contain unescaped spaces or corrupted encoding'),
            Severity.INFO if suspected else Severity.S3, Confidence.INFERRED if suspected else Confidence.VERIFIED,
            Rationale.HYPOTHESIS.value if suspected else Rationale.SELF_EVIDENT.value, INDEX_ENGINES, scope_for(urls, sitewide=True),
            {'urls': rows[:40], 'assessment': 'uncertain query intent' if suspected else 'invalid address characters'},
            'query syntax alone does not establish corruption; declared URLs preserve intended characters',
            'Compare the declared address with its original CMS record and observed destination. Repair only confirmed corruption; percent-encoding cannot recover lost letters.',
            notes=['No new request was made. A question mark can introduce a valid query; neither intended text nor server encoding was inferred.']))
    raw = [url for url in result.sitemap_urls if not_percent_encoded(url) and not malformed(url)]
    if raw:
        findings.append(Finding(
            "IDX-5", f"{len(raw)} sitemap URL(s) have letters that are not percent-encoded",
            Severity.INFO, Confidence.VERIFIED, Rationale.DOCUMENTED.value, INDEX_ENGINES, scope_for(raw, sitewide=True),
            {"urls": raw[:40]}, "every sitemap address is percent-encoded", NOT_ENCODED_FIX))
    return findings


NO_LASTMOD = "sitemap files that give no address a <lastmod>"


def sitemap_without_lastmod(docs) -> dict | None:
    """DECISIONS 363 (Efsa, enpara): every address-listing sitemap file read gives no <lastmod>, so engines cannot tell
    which pages changed. An observation (an opportunity, never a problem), or None. `docs`: SitemapDoc records or saved
    dicts."""
    def get(d, k):
        return d.get(k) if isinstance(d, dict) else getattr(d, k, None)
    files = [d for d in docs or [] if get(d, "kind") == "urlset" and (get(d, "urls_found") or 0) > 0]
    if not files or any((get(d, "lastmod_count") or 0) > 0 for d in files):
        return None
    return {"metric": NO_LASTMOD, "files": len(files), "examples": [get(d, "url") for d in files[:5]],
            "addresses": sum(get(d, "urls_found") or 0 for d in files)}


def idx5_sitemap(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "XML sitemap health"
    docs = result.sitemap_docs
    usable = [d for d in docs if d.kind in ("urlset", "sitemapindex")]
    listed = result.sitemap_urls
    site_pages = len(result.discovered_urls)
    findings: list[Finding] = []
    evidence = {"documents": [{"url": d.url, "status": d.status, "kind": d.kind, "urls_found": d.urls_found,
                               "error": d.error, "lastmod_count": d.lastmod_count,
                               "lastmod_distinct": d.lastmod_distinct, "lastmod_top": d.lastmod_top,
                               "lastmod_top_count": d.lastmod_top_count} for d in docs],
                "urls_listed": len(listed), "site_urls_discovered": site_pages,
                "discovery_notes": result.sitemap_notes}

    if not usable:
        lower_bound = result.stop_reason != StopReason.EXHAUSTED
        if site_pages > cfg.sitemap_required_above_pages:
            findings.append(Finding(
                "IDX-5", f"No usable XML sitemap on a site with {site_pages}{'+' if lower_bound else ''} discovered URLs",
                Severity.S3, Confidence.VERIFIED, "Documented (Google/Bing use sitemaps)", INDEX_ENGINES,
                scope_for([result.origin], sitewide=True), evidence,
                "a sitemap listing the pages you want indexed",
                "Publish an XML sitemap and reference it from robots.txt with a Sitemap: line.",
            ))
        findings += _failed_sitemap_files(result)
        summary = f"{len(findings)} finding(s)." if findings else (
            f"No usable sitemap, but only {site_pages} URL(s) discovered (threshold {cfg.sitemap_required_above_pages}).")
        return CheckResult("IDX-5", title, _status(findings), summary, findings, evidence)

    judged = sitemap_judgments(result, cfg)
    assessed, bad, not_self, unknown = judged["checked"], judged["not_live"], judged["canonical_elsewhere"], judged["not_checked"]
    # Review G16: a noindex page the crawl read is ACC-3's finding (its title says the sitemap lists it). Listed beside
    # the share, like canonical-elsewhere URLs, so one noindex page in the sitemap is one finding, not two.
    noindex_read = [b for b in bad if b["kind"] == "noindex" and b["source"] == "crawl"]
    bad = [b for b in bad if not (b["kind"] == "noindex" and b["source"] == "crawl")]
    evidence.update(listed_urls_assessed=len(assessed), listed_urls_not_fetched=len(unknown),
                    sitemap_check=judged["summary"])
    if noindex_read:
        evidence["noindex_reported_under_acc3"] = {"count": len(noindex_read),
                                                   "sample": [b["url"] for b in noindex_read[:20]]}
    share = len(bad) / len(assessed) if assessed else 0
    if assessed and share > cfg.sitemap_bad_share:
        urls = [b["url"] for b in bad]
        summary_of = judged["summary"]
        breakdown = {"not_live": {kind: sum(1 for b in bad if b["kind"] == kind) for kind in NOT_LIVE_KINDS},
                     "canonical_elsewhere": len(not_self), "disallowed": len(judged["disallowed"]),
                     "noindex_reported_under_acc3": len(noindex_read)}
        fields = {**evidence, "bad_urls": bad[:40], "threshold": f">{cfg.sitemap_bad_share:.0%} (spec)", "breakdown": breakdown,
                  "canonical_elsewhere": not_self[:20], "disallowed": judged["disallowed"][:20],
                  "counted": "redirects, 4xx, 5xx, empty pages and noindex seen only by a light request; canonical "
                             "elsewhere, robots.txt-disallowed URLs and noindex pages the crawl read (ACC-3 reports "
                             "them) are listed beside the share, not in it"}
        if not unknown:
            findings.append(Finding(
                "IDX-5", f"{len(bad)} of {len(assessed)} sitemap URL(s) ({share:.0%}) are not live, indexable pages",
                Severity.S3, Confidence.VERIFIED, "Documented (Google/Bing use sitemaps)", INDEX_ENGINES, scope_for(urls),
                fields, "the sitemap lists only live, indexable URLs", SHARE_FIX))
        else:
            notes = []
            if summary_of["sampled"]:
                notes.append(f"The sitemap lists {len(listed)} URLs; {len(assessed)} were checked ({summary_of['checked_by_crawl']} read "
                             f"by the crawl, {summary_of['checked_by_light_request']} with one light request each, a sample spread "
                             + (f"evenly over {summary_of['sample_files']} sitemap file(s)" if (summary_of.get("sample_files") or 0) > 1
                                else "over the site's sections")
                             + "). The share is of the URLs checked and is an estimate for the whole sitemap.")
            else:
                notes.append(f"{len(unknown)} listed URL(s) were not checked ({judged['why_not_checked']}), so the share is an "
                             "estimate from the URLs that were.")
            findings.append(Finding(
                "IDX-5", f"{len(bad)} of {len(assessed)} sitemap URL(s) checked ({share:.0%}) are not live, indexable pages; "
                         f"the sitemap lists {len(listed)}",
                Severity.S3, Confidence.ESTIMATED, "Documented (Google/Bing use sitemaps)", INDEX_ENGINES, scope_for(urls),
                fields, "the sitemap lists only live, indexable URLs", SHARE_FIX, notes=notes))
    findings += _failed_sitemap_files(result)
    findings += _malformed_sitemap_urls(result)
    findings += _draft_pages(result, set(key_page_urls(result, cfg)))

    lastmods = {u: result.sitemap_lastmods.get(u) for u in listed}
    parsed = {u: _parse_lastmod(v) for u, v in lastmods.items() if v}
    evidence.update(lastmod_present=len(parsed), lastmod_missing=sum(1 for v in lastmods.values() if not v))
    if len(parsed) >= 2 and len({v for v in parsed.values()}) == 1:
        findings.append(Finding(
            "IDX-5", f"All {len(parsed)} sitemap <lastmod> values are identical ({next(iter(parsed.values())).isoformat()})",
            Severity.S4, Confidence.VERIFIED, "Hypothesis (lastmod effect on AI freshness)", INDEX_ENGINES,
            scope_for(list(parsed), sitewide=True), {"lastmod": lastmods},
            "lastmod reflects each page's real last change",
            "Set <lastmod> from each page's actual modification date, not the sitemap generation time.",
        ))
    # One sitemap document giving (nearly) every URL the very same <lastmod>, to the second: the file's generation
    # time, not when each page changed. Seen on a real client (Midas, 2026-09-17): documents of 201 URLs sharing one
    # timestamp. Skipped when the whole sitemap is one value, which the finding above already reports.
    whole_sitemap_identical = len(parsed) >= 2 and len(set(parsed.values())) == 1
    stamped_docs = [{"sitemap": d.url, "urls": d.urls_found, "with_lastmod": d.lastmod_count,
                     "same_lastmod": d.lastmod_top_count, "value": d.lastmod_top}
                    for d in usable if d.kind == "urlset" and d.lastmod_count >= cfg.autostamp_min_pages
                    and d.lastmod_top_count / d.lastmod_count >= cfg.autostamp_share]
    if stamped_docs and not whole_sitemap_identical:
        findings.append(Finding(
            "IDX-5", f"{len(stamped_docs)} sitemap document(s) give (nearly) every URL the same <lastmod>",
            Severity.S4, Confidence.VERIFIED, "Hypothesis (lastmod effect on AI freshness)", INDEX_ENGINES,
            # A sitemap document is a file, not a page: a problem with it is a problem of the whole site.
            scope_for([d["sitemap"] for d in stamped_docs], sitewide=True), {"documents": stamped_docs[:40],
                                                               "share_threshold": cfg.autostamp_share},
            "each URL's lastmod is when that page last changed",
            "Set <lastmod> per URL from the page's real last edit, not the time the sitemap file was generated.",
            notes=["Verified: the values are as listed. That they are the file's generation time rather than real "
                   "edits is Inferred from every URL in the document sharing one timestamp.",
                   "Capped at S4: Hypothesis."]))
    future = {u: v.isoformat() for u, v in parsed.items() if v > datetime.now(timezone.utc) + timedelta(days=1)}
    if future:
        findings.append(Finding(
            "IDX-5", f"{len(future)} sitemap <lastmod> value(s) are in the future", Severity.S4, Confidence.VERIFIED,
            "Hypothesis (lastmod effect on AI freshness)", INDEX_ENGINES, scope_for(list(future)),
            {"future_lastmod": future}, "lastmod is never later than now",
            "Fix the date source for <lastmod>; future dates are likely a time-zone or formatting bug.",
        ))
    observations = ([{"metric": "sitemap URLs that canonicalize elsewhere", "value": len(not_self),
                      "sample": not_self[:20]}] if not_self else [])
    no_lastmod = sitemap_without_lastmod(result.sitemap_docs)  # DECISIONS 363
    if no_lastmod:
        observations.append(no_lastmod)
    summary = (f"{len(findings)} finding(s) for {len(listed)} listed URL(s)." if findings
               else f"{len(usable)} sitemap document(s), {len(listed)} URL(s); {len(assessed)} of them fetched and none "
                    f"failing thresholds" + (f"; {len(unknown)} listed URL(s) not fetched, so not judged." if unknown
                                             else "."))
    sampled_of = (judged or {}).get("summary") or {} if listed else {}
    if sampled_of.get("sampled"):
        # Said whether or not there is a finding: the light requests were a sample, and how many (DECISIONS 294).
        files = sampled_of.get("sample_files") or 0
        summary += (f" A sample was checked: {sampled_of.get('checked_by_light_request', 0)} of the {sampled_of.get('wanted') or 0} "
                    "sitemap URL(s) the crawl did not read, spread "
                    + (f"evenly over {files} sitemap file(s)." if files > 1 else "over the site's sections."))
    from ..evidence_accuracy import scope_sentence
    scope_note = scope_sentence("IDX-5", evidence)
    if scope_note: summary += " " + scope_note
    return CheckResult("IDX-5", title, _status(findings), summary, findings, evidence, observations)


# -- IDX-6 -------------------------------------------------------------------

def tracking_parameters(url: str) -> list[str]:
    """Analytics parameters in a URL's query string, as written ("utm_source=gemini")."""
    return [f"{key}={value}" for key, value in parse_qsl(urlsplit(url).query, keep_blank_values=True)
            if key.lower() in TRACKING_PARAMETERS or key.lower().startswith(TRACKING_PARAMETER_PREFIXES)]


CLOUDFLARE_EMAIL_FIX = ("Nothing to fix if hiding the address from scrapers is intended. For an address meant to be "
                        "read and quoted, turn off Email Address Obfuscation in Cloudflare (Scrape Shield), or leave it "
                        "out with the email_off comments around it.")


# Said after IDX-1's 4xx title when IDX-6's per-target findings for the same dead URLs are folded into it
# (maya_audit.root_cause, review H10): one dead URL is one finding.
IDX6_SUFFIX = "; linked from {pages} page(s)"
BROKEN_TARGET_TITLE = re.compile(r"^Link target returns (?P<status>\d+), linked from")
REFERENCED_4XX_TITLE = re.compile(r"return a client error \(4xx\), linked internally or listed in the sitemap")


def idx6_broken_links(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Internal links: broken targets and tracking parameters"
    key_urls = set(key_page_urls(result, cfg))
    by_url = {p.url: p for p in result.pages}
    transient = set()  # failed in the crawl but answered below 500 on another attempt: not a broken link
    for url, attempts in attempts_by_url(result).items():
        crawl = [a for a in attempts if a["source"] == "crawl"]
        if crawl and failed(crawl[0]) and any(counted(a) and not failed(a) for a in attempts if a["source"] != "crawl"):
            transient.add(url)
    edges: dict[str, list[dict]] = defaultdict(list)
    for page in result.pages:
        for edge in page.outlinks:
            target = by_url.get(edge["target"])
            # A CDN's own machinery (/cdn-cgi/, /akam/, /_vercel/ ...) is not a page of the site (review H09, G06).
            if (target and target.fetch_class == FetchClass.OK and target.status and target.status >= 400
                    and target.url not in transient and not edge_machinery(target.url)):
                edges[edge["target"]].append({"source": page.url, "anchor": edge["anchor"]})
    findings = []
    for target, sources in sorted(edges.items()):
        page = by_url[target]
        source_urls = [s["source"] for s in sources]
        findings.append(Finding(
            "IDX-6", f"Link target returns {page.status}, linked from {len(sources)} page(s): {target}", Severity.S3,
            Confidence.VERIFIED, "Documented (discovery)", ALL_ENGINES, scope_for(source_urls),
            {"target": target, "target_status": page.status, "links": sources[:40], "reproduce": _curl(target, cfg)},
            "internal links point at live URLs",
            "Update these links to the correct live URL or remove them. If the target should exist, that is the "
            "IDX-1 finding on the target.",
            importance_tier=_tier(source_urls + [target], key_urls),
        ))
    total = sum(len(v) for v in edges.values())
    broken = len(findings)

    # Cloudflare's e-mail obfuscation (review H09): the address is swapped for a link to /cdn-cgi/l/email-protection and
    # put back by a script. Not a broken link; a note that a reader without JavaScript cannot see the address.
    hidden = cloudflare_email_pages(result)
    if hidden:
        sources = [row["url"] for row in hidden]
        findings.append(Finding(
            "IDX-6", "Cloudflare e-mail obfuscation is on: the address is readable only with JavaScript", Severity.INFO,
            Confidence.VERIFIED, Rationale.SELF_EVIDENT.value, ALL_ENGINES, scope_for(sources),
            {"pages": hidden[:40], "pages_count": len(hidden)},
            "a contact address a reader and a crawler can read without running a script", CLOUDFLARE_EMAIL_FIX,
            importance_tier=_tier(sources, key_urls),
            notes=["Verified: the pages carry Cloudflare's replacement for an e-mail address. Not tested: which crawlers "
                   "and assistants run the script that puts the address back."]))

    # Links from the site to itself that carry analytics parameters (seen live: ?utm_source=gemini on five
    # links of a service page, pasted in with text an assistant wrote).
    tagged = []
    for page in result.pages:
        for edge in page.outlinks:
            params = tracking_parameters(edge["target"])
            if params:
                tagged.append({"source": page.url, "target": edge["target"], "parameters": params, "anchor": edge["anchor"]})
    if tagged:
        sources = sorted({row["source"] for row in tagged})
        values = list(dict.fromkeys(p for row in tagged for p in row["parameters"]))
        findings.append(Finding(
            "IDX-6", f"{len(tagged)} internal link(s) on {len(sources)} page(s) carry tracking parameters "
                     f"({', '.join(values[:4])}{' ...' if len(values) > 4 else ''})", Severity.S3, Confidence.VERIFIED,
            "Documented (Google: use consistent internal links; campaign parameters are for links from outside)",
            ALL_ENGINES, scope_for(sources),
            {"links": tagged[:60], "links_count": len(tagged), "parameters": values[:20]},
            "links inside a site point at the page's plain address",
            "Remove the parameters from these links. On an internal link they give the page a second address for "
            "crawlers to find, and they overwrite the visitor's real source in analytics.",
            importance_tier=_tier(sources, key_urls)))
    # Links to another site whose path is a page of this one: often an internal link pasted in with the wrong domain
    # (seen live: article links pointing at the content tool's domain instead of the hospital's). The path alone does
    # not show where the link leads, so each distinct address was asked once (index_data.check_other_site_targets,
    # DECISIONS 196): it answers with a page or a redirect, nothing is reported; 404 or 410, the link is dead; anything
    # else, a note that it could not be checked. A link to a brand-family domain is never looked at.
    misplaced, family_skipped = misplaced_links(result, cfg)
    index = getattr(result, "index", None)
    asked = dict(getattr(index, "other_site_targets", None) or {})
    groups: dict[object, list[dict]] = defaultdict(list)
    answering = 0
    for row in misplaced:
        seen = asked.get(row["target"]) or {}
        status = seen.get("status") if seen.get("checked") else None
        if status in (404, 410):
            groups[status].append({**row, "other_address_status": status})
        elif status is not None and 200 <= status < 400:
            answering += 1
        else:
            groups[None].append({**row, "other_address": (f"answered {status}" if status is not None else
                                                          seen.get("reason") or "not requested")})
    for status in sorted((key for key in groups if key is not None)):
        rows = groups[status]
        sources = sorted({row["source"] for row in rows})
        hosts = sorted({row["other_site"] for row in rows})
        findings.append(Finding(
            "IDX-6", f"{len(rows)} link(s) on {len(sources)} page(s) point to another site ({', '.join(hosts[:3])}) "
                     f"at a path that exists on this one, and the other address returns {status}", Severity.S3, Confidence.VERIFIED,
            "Self-evident harm (the reader is sent to a page that is not there) / Documented (internal linking)",
            ALL_ENGINES, scope_for(sources),
            {"links": rows[:60], "links_count": len(rows), "other_sites": hosts, "other_address_status": status,
             "reproduce": _curl(rows[0]["target"], cfg)},
            "a link to one of the site's own pages uses the site's own address",
            "Change these links to the address on this site. The other address answers with an error, and the same path "
            "is a page of this site.",
            importance_tier=_tier(sources, key_urls),
            notes=["Verified: the link's path is the path of a page found on this site, and the other address was "
                   f"requested once and returned {status}. Inferred: that the link was meant to be internal."]))
    if groups[None]:
        rows = groups[None]
        sources = sorted({row["source"] for row in rows})
        hosts = sorted({row["other_site"] for row in rows})
        findings.append(Finding(
            "IDX-6", f"{len(rows)} link(s) on {len(sources)} page(s) point to another site ({', '.join(hosts[:3])}) "
                     "at a path that exists on this one; the other address could not be checked", Severity.INFO, Confidence.INFERRED,
            Rationale.SELF_EVIDENT.value, ALL_ENGINES, scope_for(sources),
            {"links": rows[:60], "links_count": len(rows), "other_sites": hosts,
             "why_not_checked": sorted({row["other_address"] for row in rows})[:10]},
            "a link to one of the site's own pages uses the site's own address",
            "Open one of these links. If it does not show the page you meant, change the link to the address on this site. "
            "If the other site belongs to the same brand, add its domain to the brand's other domains and this is not reported.",
            importance_tier=_tier(sources, key_urls),
            notes=["Verified: the link's path is the path of a page found on this site. Not known: whether the other "
                   "address leads to a page, because it could not be requested or did not give a clear answer."]))
    # Links to other sites (DECISIONS 211): each address asked once with a HEAD; only 404 or 410 is a dead link, and an
    # address IDX-6 already reports above (another site at one of this site's paths) is not reported twice.
    structure = getattr(result, "structure", None)
    asked_other = dict(getattr(structure, "other_site_links", None) or {})
    already = {row["target"] for row in misplaced}
    cycles = [row for url, row in asked_other.items() if row.get("verdict") == "redirect_loop" and url not in already]
    if cycles:
        sources = sorted({page for row in cycles for page in row["pages"]})
        findings.append(Finding("IDX-6", f"{len(cycles)} external destination(s) produced a GET redirect cycle for the recorded client",
            Severity.S4, Confidence.VERIFIED, Rationale.MEASURED.value, ALL_ENGINES, scope_for(sources),
            {"links": cycles, "targets_count": len(cycles), "qualification": "observed request-specific cycle; not universal or persistent access proof"},
            "linked destinations complete their redirects for the tested client",
            "Inspect the recorded GET chain and reproduce it in the same client context before changing the link or redirect configuration.",
            importance_tier=_tier(sources, key_urls), notes=["One bounded request walk; other clients and observation times may differ."]))
    dead = [row for url, row in asked_other.items() if row.get("verdict") == "broken" and url not in already]
    if dead:
        sources = sorted({page for row in dead for page in row["pages"]})
        links = sum(row["links"] for row in dead)
        findings.append(Finding(
            "IDX-6", f"{links} link(s) to other sites on {len(sources)} page(s) return 404 or 410", Severity.S4,
            Confidence.VERIFIED, "Self-evident harm (the reader is sent to a page that is not there)", ALL_ENGINES,
            scope_for(sources),
            {"links": [{"target": row["url"], "status": row.get("status"), "method": row.get("method"),
                        "linked_from": row["pages"], "linked_from_count": row["pages_count"], "anchor": row.get("anchor"),
                        "requested_at": row.get("requested_at"), "attempts": row.get("attempts"), "final_url": row.get("final_url"), "reproduce": f"curl -L -A {shlex.quote(cfg.user_agent)} {shlex.quote(row['url'])}"}
                       for row in dead[:60]],
             "targets_count": len(dead), "links_count": links,
             "broken": "GET-confirmed 404 or 410; bounded redirect outcomes and unavailable corroboration are recorded separately"},
            "links to other sites lead to pages that exist",
            "Update or remove these links; the pages they point to are gone.",
            importance_tier=_tier(sources, key_urls)))
    unchecked_other = dict(getattr(structure, "other_site_links_not_checked", None) or {})
    summary = (f"{broken} broken target(s) behind {total} internal link(s)." if broken
               else "No internal link points at a 4xx/5xx URL that was fetched.")
    summary += (f" {len(misplaced)} link(s) to another site use the path of a page on this one." if misplaced else "")
    if structure is not None and getattr(structure, "external_links_enabled", False):
        checked_other = sum(1 for row in asked_other.values() if row.get("checked"))
        summary += (f" Links to other sites: {checked_other} checked, {len(dead)} gone (404 or 410), "
                    f"{sum(unchecked_other.values())} not checked.")
    elif structure is not None:
        summary += " Links to other sites were not checked (--no-external-links)."
    summary += (f" {len(tagged)} internal link(s) carry tracking parameters." if tagged
                else " No internal link carries tracking parameters.")
    return CheckResult("IDX-6", title, _status(findings), summary, findings,
                       {"internal_edges": sum(len(p.outlinks) for p in result.pages),
                        "excluded_transient_5xx_targets": sorted(transient),
                        "internal_links_with_tracking_parameters": len(tagged),
                        "links_to_another_site_at_one_of_this_sites_paths": len(misplaced),
                        "of_which_the_other_address_answers_with_a_page_or_a_redirect": answering,
                        "links_to_brand_family_domains_not_checked": family_skipped,
                        "brand_family_domains": list(cfg.brand_family_domains),
                        "other_site_requests": sum(1 for seen in asked.values() if seen.get("requested_at")),
                        "external_links_seen": sum(len(p.external_links or []) for p in result.pages),
                        # The other-site check (DECISIONS 211): addresses of other sites linked from the pages read.
                        "other_site_links": {
                            "enabled": bool(getattr(structure, "external_links_enabled", False)),
                            "addresses": getattr(structure, "other_site_link_candidates", 0),
                            "asked": len(asked_other),
                            "working": sum(1 for row in asked_other.values() if row.get("verdict") == "works"),
                            "gone": len(dead),
                            "not_checked": unchecked_other,
                            "not_checked_because": {k: REASONS.get(k, k) for k in unchecked_other}}},
                       _external_link_parameters(result, cfg))


# P3: parameters a link to another site should not carry because they were copied from a browser's address bar: click
# identifiers (fbclid, gclid…) and the ones a logged-in view adds to a profile address (seen live: a LinkedIn company
# page with ?viewAsMember=true). utm_* on a link to another site is the linking site's own referral tagging, on
# purpose (seen live: a platform's "powered by" footer link): not noted.
VIEW_PARAMETERS = frozenset({"viewasmember", "igsh", "igshid"})
EXTERNAL_LINK_PARAMETERS = "links to other sites that carry tracking or logged-in view parameters"


def _external_link_parameters(result: CrawlResult, cfg: CrawlConfig) -> list[dict]:
    """An IDX-6 observation (a client report may raise it): the links to other sites whose address carries a click
    identifier or a logged-in view parameter, each with the parameters and how many pages link to it."""
    from ..structure_data import other_site_link_targets

    rows = []
    for row in other_site_link_targets(result, cfg):
        found = [f"{key}={value}" for key, value in parse_qsl(urlsplit(row["url"]).query, keep_blank_values=True)
                 if key.lower() in TRACKING_PARAMETERS or key.lower() in VIEW_PARAMETERS]
        if found:
            rows.append({"url": row["url"], "parameters": found, "pages": len(row["pages"]), "example": row["pages"][0]})
    return [{"metric": EXTERNAL_LINK_PARAMETERS, "links": len(rows), "examples": rows[:10],
             "note": "Link to the clean address: the parameters are the linking browser's, not part of the page."}] if rows else []


# -- IDX-7 -------------------------------------------------------------------

def idx7_discoverability(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    from ..link_graph import build_link_graph
    from .integrity import int2_crawl_completeness

    title = "Discoverability: orphans, click depth and inbound links"
    key_urls = set(key_page_urls(result, cfg))
    int2 = int2_crawl_completeness(result, cfg)
    complete = int2.state == "complete"
    graph = build_link_graph(result)
    readable = [p for p in result.pages if _readable_html(p)]
    findings: list[Finding] = []
    discovery = getattr(result, "render_discovery", None) or {}
    evidence = {"crawl_complete": complete, "int2_summary": int2.summary, "homepage": graph.homepage,
                "links_known_only_from_a_rendered_view": graph.rendered_only,
                "render_discovery": {k: discovery.get(k) for k in ("enabled", "reason", "used", "pages_rendered", "links_added")},
                "depth_method": "fewest clicks from the homepage over the links of the fetched pages (breadth-first); "
                                "a link to a redirecting URL counts for the page the redirect ends on"}
    incomplete_note = ("The crawl is incomplete, so these figures cover the fetched pages only: a page may have more "
                       "links to it, and a shorter path to it, than is shown.")

    if graph.js_linked:
        # A page nobody links to in the pages that were rendered may be linked from one that was not.
        orphan_status = ("not assessed: this site writes links with JavaScript (" + graph.js_linked_why + "), and only "
                         "some pages were rendered, so a page without a known link may still be linked")
        evidence["unlinked_sitemap_pages_not_called_orphans"] = len(
            [p for p in readable if p.discovered_via == "sitemap" and not graph.inbound_count(p.url)])
    elif complete:
        # A draft or test page is said once, under IDX-5 (review H13): never told to be linked to.
        drafts = {row["url"] for row in draft_pages(result)}
        orphans = [p.url for p in readable if p.discovered_via == "sitemap" and not graph.inbound_count(p.url)
                   and p.url not in drafts]
        if drafts:
            evidence["draft_pages_left_out"] = {"count": len(drafts), "reported_under": "IDX-5"}
        if orphans:
            def build(its, severity, intent):
                urls = [u for u, _ in its]
                return Finding(
                    "IDX-7", f"{len(urls)} page(s) are listed only in the sitemap, with no internal links to them",
                    severity, Confidence.VERIFIED, Rationale.HYPOTHESIS.value, INDEX_ENGINES, scope_for(urls),
                    {"orphans": urls[:40]}, "pages meant to be found are linked from other pages",
                    "Link to these pages from relevant pages, or mark them as intended (e.g. campaign landing pages).",
                    intent=intent, importance_tier=_tier(urls, key_urls),
                    notes=["Capped at S4: Hypothesis.", *int2.evidence.get("caveats", [])],
                )
            findings += _with_intent("IDX-7", "orphan", [(u, None) for u in orphans], Severity.S4, key_urls, cfg, build)
        orphan_status = "assessed"
    else:
        orphan_status = f"not assessed: crawl incomplete ({int2.summary})"
    evidence["orphans"] = orphan_status

    rows = sorted(({"url": p.url, "click_depth": graph.depth.get(p.url), "inbound_links": graph.inbound_count(p.url)}
                   for p in readable), key=lambda row: row["url"])
    deep = sorted((row for row in rows if row["click_depth"] is not None and row["click_depth"] >= cfg.deep_page_depth),
                  key=lambda row: (-row["click_depth"], row["url"]))
    if deep:
        urls = [row["url"] for row in deep]
        findings.append(Finding(
            "IDX-7", f"{len(urls)} page(s) are {cfg.deep_page_depth}+ clicks from the homepage", Severity.INFO,
            Confidence.VERIFIED if complete else Confidence.ESTIMATED, Rationale.HYPOTHESIS.value, INDEX_ENGINES,
            scope_for(urls),
            {"pages": [{"url": row["url"], "depth": row["click_depth"]} for row in deep[:40]],
             "deepest": deep[0]["click_depth"], "threshold": cfg.deep_page_depth},
            "important pages within a few clicks of the homepage",
            "Link important deep pages from hub or navigation pages.", importance_tier=_tier(urls, key_urls),
            notes=[] if complete else [incomplete_note],
        ))
    others = [row for row in rows if row["url"] != graph.homepage]
    observations = []
    if others:
        by_inbound = sorted(others, key=lambda row: (-row["inbound_links"], row["url"]))
        histogram: dict[str, int] = defaultdict(int)
        for row in rows:
            histogram["not reached by links" if row["click_depth"] is None else str(row["click_depth"])] += 1
        observations.append({
            "metric": "internal links pointing to each page (distinct linking pages)", "pages": len(rows),
            "most_linked": by_inbound[:10], "least_linked": sorted(others, key=lambda row: (row["inbound_links"], row["url"]))[:10],
            "pages_by_click_depth": dict(sorted(histogram.items())),
            "note": None if complete else incomplete_note})
    evidence["link_graph"] = {"pages": rows[:1000], "pages_total": len(rows), "pages_listed": min(len(rows), 1000)}
    if not findings and orphan_status != "assessed" and not rows:
        return CheckResult("IDX-7", title, "not_assessed", f"Orphans {orphan_status}; no deep pages found.", evidence=evidence)
    # Click depth was measured even when orphans could not be judged: a pass on depth with the orphan question
    # open, which the coverage rule turns into "partial".
    summary = (f"{len(findings)} finding(s); orphans {orphan_status}." if findings else
               "No orphans or deep pages." if orphan_status == "assessed" else f"No deep pages; orphans {orphan_status}.")
    return CheckResult("IDX-7", title, _status(findings), summary, findings, evidence, observations)


# -- IDX-8 -------------------------------------------------------------------

VARIANT_FIX = "Add what sets each variant apart (ingredients, weight, use), or create a parent product page."
VARIANT_NOTE = "These pages look like variants of one product: their addresses and titles differ by a word or two."
# How many words two variant pages may differ by, on each side, and how many they must share. The owner said "1-2
# words"; three are allowed in an address because one saved group differs by three there ("bol-antep-fistikli-dag-…"
# beside "narli-dag-…"). Agent defaults from one site, not calibrated (decision 190; LAUNCH-GATE).
VARIANT_SHARED_WORDS = 2
VARIANT_TITLE_WORDS = 2
VARIANT_URL_WORDS = 3
_TITLE_PARTS = re.compile(r"\s+[|\-–—·•:]\s+")  # the separators STR-5 reads a site name after


def _words(text: str) -> list[str]:
    """Words compared without case or Turkish letter marks: "Fıstıklı" and "fistikli" are one word."""
    return fold_text(text).replace("_", " ").split()


def _own_title_parts(title: str, other: str) -> str:
    """`title` without the parts it ends with that `other` ends with too: a site name after a title separator."""
    mine, theirs = _TITLE_PARTS.split(title.strip()), _TITLE_PARTS.split(other.strip())
    while len(mine) > 1 and len(theirs) > 1 and fold_text(mine[-1]) == fold_text(theirs[-1]):
        mine.pop()
        theirs.pop()
    return " ".join(mine)


def _differing(a: list[str], b: list[str], most: int) -> dict[str, list[str]] | None:
    """The words only `a` and only `b` have, when they share enough and differ by 1 to `most` on each side."""
    shared = set(a) & set(b)
    only_a, only_b = [w for w in dict.fromkeys(a) if w not in shared], [w for w in dict.fromkeys(b) if w not in shared]
    if len(shared) >= VARIANT_SHARED_WORDS and 1 <= len(only_a) <= most and 1 <= len(only_b) <= most:
        return {"a": only_a, "b": only_b}
    return None


def variant_difference(url_a: str, title_a: str, url_b: str, title_b: str) -> dict[str, dict[str, list[str]]] | None:
    """{"url": {"a": [...], "b": [...]}, "title": {...}}: the words two pages differ by, when they look like variants
    of one product: the same folder at the same depth, last address segments that share two words or more and differ
    by one to three on each side, and titles (without the site name) that share two and differ by one or two.
    None when any of that does not hold."""
    parts_a = [part for part in urlsplit(url_a).path.split("/") if part]
    parts_b = [part for part in urlsplit(url_b).path.split("/") if part]
    if not parts_a or len(parts_a) != len(parts_b) or parts_a[:-1] != parts_b[:-1]:
        return None
    in_url = _differing(_words(unquote(parts_a[-1])), _words(unquote(parts_b[-1])), VARIANT_URL_WORDS)
    in_title = _differing(_words(_own_title_parts(title_a, title_b)), _words(_own_title_parts(title_b, title_a)), VARIANT_TITLE_WORDS)
    return {"url": in_url, "title": in_title} if in_url and in_title else None


def _swapped(found: dict[str, dict[str, list[str]]]) -> dict[str, dict[str, list[str]]]:
    return {where: {"a": sides["b"], "b": sides["a"]} for where, sides in found.items()}


TWO_ADDRESSES_FIX = ("Choose one address for each page and redirect the other to it with a 301, or point the other's "
                     "canonical at it; link only to the chosen one.")
# What root_cause reads to say a pair once (review H20).
TWO_ADDRESSES_TITLE = re.compile(r"page\(s\) are reachable at two addresses")
DUPLICATES_FIX = ("For each group, keep one page and redirect the others to it, or give each page its own text, title and "
                  "description.")


def idx8_merged(groups: list[dict], urls: list[str], *, near: bool, variant: bool, evidence: dict, launch_gated: list[str],
                importance_tier: int) -> Finding:
    """IDX-8's groups of identical and nearly identical pages as one finding, a line for each group (maya_audit.root_cause,
    DECISIONS 225). `groups`: [{"urls", "signals", "same_text_pages", "variant_like", "pairs"}]."""
    return Finding(
        "IDX-8", f"{len(groups)} {'group' if len(groups) == 1 else 'groups'} of indexable pages that are copies or near-copies of each other ({len(urls)} pages)",
        Severity.S4, Confidence.ESTIMATED if near else Confidence.VERIFIED, Rationale.HYPOTHESIS.value, INDEX_ENGINES,
        scope_for(urls), {**evidence, "duplicate_groups": groups, "urls": urls},
        "each indexable URL has distinct content", DUPLICATES_FIX, launch_gated=launch_gated, importance_tier=importance_tier,
        notes=["Capped at S4: Hypothesis.",
               *(["Similarity is an estimate; the threshold is a round number, not calibrated."] if near else []),
               *([VARIANT_NOTE] if variant else [])])


DOORWAY_DOC = ("Documented (Google spam policies, doorway abuse: many pages for different places that differ only by the "
               "place name)")


def _location_templates(candidates: list, own_words: dict[str, list[str]], cfg: CrawlConfig, key_urls: set[str]) -> list:
    """DECISIONS 264: pages under one path section whose own text differs mostly by the place name in their address
    (/sube/kadikoy/, /semt/uskudar/). The words of each page's own last path segment are masked before comparing, so
    "Kadıköy" against "Üsküdar" no longer keeps two template copies under the near-duplicate threshold."""
    by_section = defaultdict(list)
    for p in candidates:
        segments = [s for s in urlsplit(p.url).path.split("/") if s]
        if len(segments) >= 2:
            by_section[segments[0]].append(p)
    out = []
    for section, pages in sorted(by_section.items()):
        if len(pages) < cfg.location_template_min_pages:
            continue
        masked = {}
        for p in pages:
            slug = [s for s in urlsplit(p.url).path.split("/") if s][-1]
            place = set(fold_text(unquote(slug).replace("-", " ").replace("_", " ")).split())
            words = [w for w in own_words.get(p.url, []) if fold_text(w) not in place]
            if len(words) >= MIN_MAIN_WORDS_TO_COMPARE:
                masked[p.url] = text_sketch(words)
        alike, best = set(), {}
        urls = sorted(masked)
        for i, a in enumerate(urls):
            for b in urls[i + 1:]:
                sim = sketch_similarity(masked[a], masked[b])
                if sim is not None and sim >= cfg.same_content_similarity:
                    alike.update((a, b))
                    for u, v in ((a, b), (b, a)):
                        if sim > best.get(u, (0, None))[0]:
                            best[u] = (round(sim, 3), v)
        if len(alike) < cfg.location_template_min_pages or len(alike) < 0.5 * len(urls):
            continue
        found = sorted(alike)
        out.append(Finding(
            "IDX-8", f"{len(found)} pages under /{section}/ differ mostly by the place name in their address",
            Severity.S3, Confidence.ESTIMATED, DOORWAY_DOC, INDEX_ENGINES, scope_for(found),
            {"section": f"/{section}/", "pages_in_section": len(pages), "compared": len(urls),
             "closest": [{"url": u, "most_alike": best[u][1], "estimated_similarity": best[u][0]} for u in found[:40]],
             "threshold": cfg.same_content_similarity, "method": "bottom-k sketch of 5-word shingles, the address's own "
             "words masked", "compared_text": MAIN_CONTENT_BASIS},
            "each place page says something only true of that place (opening hours, menu, address, people, reviews)",
            "Give each page content that is specific to its place, or keep one page that lists the places and remove "
            "or noindex the thin copies.", importance_tier=_tier(found, key_urls),
            notes=["Estimated: similarity is a sketch, and the place name is masked from the address's own words only.",
                   "Medium by policy (DECISIONS 264): many near-identical place pages can be treated as doorway pages."]))
    return out


LOCATION_RULE = "idx8.location_template"


def location_template_kept(urls: list[str], types: dict[str, str | None], location_ids: frozenset[str],
                           min_pages: int) -> bool:
    """DECISIONS 329: a "pages differ mostly by the place name" group stands only on real location pages: the business
    type has location page types (clinic, branch, store, dealer, service area) and at least `min_pages` of the group's
    pages, and at least half of them, are typed as one. enpara's FAQ (/sss/) and payment (/odemeler/) pages are not."""
    if not location_ids or not urls:
        return False
    places = [u for u in urls if types.get(u) in location_ids]
    return len(places) >= min_pages and 2 * len(places) >= len(urls)


def _field(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def gate_location_templates(checks, types: dict[str, str | None], profile_id: str | None, min_pages: int | None = None,
                            ) -> list[dict]:
    """Remove the IDX-8 place-name groups that are not on location pages (`location_template_kept`), from engine checks
    (`CheckResult`) or a saved report's checks (dicts). Returns what was left out; the check's evidence keeps it, its
    summary count follows, and a check left with no finding passes (or is partial, as its coverage says)."""
    from ..business_types import location_types
    location_ids = location_types(profile_id)
    least = int(min_pages if min_pages is not None else CrawlConfig.location_template_min_pages)
    left_out: list[dict] = []
    for check in checks or []:
        if _field(check, "check_id") != "IDX-8":
            continue
        findings = list(_field(check, "findings") or [])
        keep, dropped = [], []
        for f in findings:
            if _field(f, "rule_id") == LOCATION_RULE:
                urls = list((_field(f, "scope") or {}).get("urls") or [])
                if not location_template_kept(urls, types, location_ids, least):
                    section = (_field(f, "evidence") or {}).get("section")
                    dropped.append({"finding_id": _field(f, "id"), "section": section, "pages": len(urls),
                                    "page_types": sorted({str(types.get(u) or "not typed") for u in urls}),
                                    "reason": ("the business type has no location page type" if not location_ids else
                                               "its pages are not location pages of the business type"),
                                    "decision": "DECISIONS 329"})
                    continue
            keep.append(f)
        if not dropped:
            continue
        left_out += dropped
        summary = _field(check, "summary") or ""
        m = re.search(r"(\d+) duplicate group\(s\) among", summary)
        if m:
            n = max(0, int(m.group(1)) - len(dropped))
            summary = summary[:m.start()] + (f"{n} duplicate group(s) among" if n else "No duplicate groups among") + summary[m.end():]
        summary += (f" {len(dropped)} place-name group(s) left out: their pages are not location pages of the business "
                    "type (DECISIONS 329).")
        evidence = _field(check, "evidence")
        if isinstance(evidence, dict):
            evidence["location_templates_left_out"] = dropped
        status = _field(check, "status")
        if not keep and status == "findings":
            coverage = _field(check, "coverage") or {}
            status = "partial" if coverage.get("not_assessed") else "pass"
        if isinstance(check, dict):
            check.update(findings=keep, summary=summary, status=status)
        else:
            check.findings, check.summary, check.status = keep, summary, status
    return left_out


def idx8_duplicates(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Duplicate and near-duplicate pages"
    key_urls = set(key_page_urls(result, cfg))
    candidates = []
    for page in result.pages:
        if not (_readable_html(page) and page.content_checks_eligible and page.analysis["visible_words"]):
            continue
        if noindex_directives(page.analysis, page.headers):
            continue
        if canonical_elsewhere(page):
            continue
        candidates.append(page)

    findings: list[Finding] = []
    # One page at two addresses (review H20) is its own finding, and a draft page is IDX-5's (H13): neither is compared
    # again below, so the same pair or draft is not also a group of copies.
    pairs = address_pairs(candidates)
    if pairs:
        urls = list(dict.fromkeys(url for pair in pairs for url in pair["urls"]))
        findings.append(Finding(
            "IDX-8", f"{len(pairs)} page(s) are reachable at two addresses", Severity.S4, Confidence.VERIFIED,
            "Documented (Google: one URL per page; consolidate duplicates with rel=canonical or a redirect)", INDEX_ENGINES,
            scope_for(urls), {"pairs": pairs[:40], "comparison": "text hash",
                              "rule": "the same path with or without a trailing slash or a file extension (.aspx, .php, "
                                      ".html), or in another letter case, with the same visible text, and neither "
                                      "address names the other as canonical or redirects to it"},
            "each page answers at one address", TWO_ADDRESSES_FIX, importance_tier=_tier(urls, key_urls)))
    left_out = {pair["other"] for pair in pairs} | {row["url"] for row in draft_pages(result)}
    candidates = [page for page in candidates if page.url not in left_out]
    # A title two pages share is STR-1's finding, once: it is not reported here as well (decision 187).
    by_hash = defaultdict(list)
    for page in candidates:
        by_hash[page.analysis["text_sha256"]].append(page.url)

    exact_groups = [sorted(urls) for urls in by_hash.values() if len(urls) > 1]
    for urls in exact_groups:
        findings.append(Finding(
            "IDX-8", f"{len(urls)} indexable pages have identical visible text", Severity.S4, Confidence.VERIFIED,
            Rationale.HYPOTHESIS.value, INDEX_ENGINES, scope_for(urls), {"urls": urls, "comparison": "text hash"},
            "each indexable URL has distinct content",
            "Pick one URL, redirect or canonicalize the others to it.", importance_tier=_tier(urls, key_urls),
            notes=["Capped at S4: Hypothesis."],
        ))
    # Near-duplicates (Estimated): union pages whose estimated similarity passes the threshold.
    parent = {p.url: p.url for p in candidates}

    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    # Compared on each page's own content. On the whole visible text, two unrelated pages of a site with a large
    # menu and footer come out ~90% alike (seen on a live site: a demo form, an about page and a blog post).
    repeated = repeated_blocks(candidates)
    own_words = {p.url: main_words(p.analysis, repeated) for p in candidates}
    sketches = {url: text_sketch(words) for url, words in own_words.items() if len(words) >= MIN_MAIN_WORDS_TO_COMPARE}
    too_short = sorted(url for url, words in own_words.items() if len(words) < MIN_MAIN_WORDS_TO_COMPARE)
    near_pairs = []
    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            if a.analysis["text_sha256"] == b.analysis["text_sha256"]:
                continue
            sim = sketch_similarity(sketches.get(a.url) or [], sketches.get(b.url) or [])
            if sim is not None and sim >= cfg.same_content_similarity:
                near_pairs.append({"a": a.url, "b": b.url, "estimated_similarity": round(sim, 3)})
                parent[find(a.url)] = find(b.url)
    clusters = defaultdict(list)
    for pair in near_pairs:
        for u in (pair["a"], pair["b"]):
            if u not in clusters[find(u)]:
                clusters[find(u)].append(u)
    titles = {p.url: p.analysis["title"] or "" for p in candidates}
    for urls in clusters.values():
        urls = sorted(urls)
        # Pages whose addresses and titles differ by a word or two (one product in several flavours) are not asked to
        # be merged: they are asked to say what sets each apart (decision 190).
        differences = {(a, b): variant_difference(a, titles[a], b, titles[b]) for i, a in enumerate(urls) for b in urls[i + 1:]}
        variant_like = all(found is not None for found in differences.values())
        pairs = [dict(p) for p in near_pairs if p["a"] in urls][:40]
        if variant_like:
            for pair in pairs:
                pair["differs_in"] = differences.get((pair["a"], pair["b"])) or _swapped(differences[(pair["b"], pair["a"])])
        findings.append(Finding(
            "IDX-8", f"{len(urls)} indexable pages have nearly identical main content (estimate)", Severity.S4,
            Confidence.ESTIMATED, Rationale.HYPOTHESIS.value, INDEX_ENGINES, scope_for(urls),
            {"urls": urls, "pairs": pairs, "variant_like": variant_like, "titles": {u: titles[u] for u in urls},
             "threshold": cfg.same_content_similarity, "method": "bottom-k sketch of 5-word shingles",
             "compared": MAIN_CONTENT_BASIS, "main_content_words": {u: len(own_words[u]) for u in urls}},
            "each indexable URL has distinct content",
            VARIANT_FIX if variant_like else "Consolidate near-identical pages, or make each one clearly distinct.",
            importance_tier=_tier(urls, key_urls),
            notes=["Capped at S4: Hypothesis.", "Similarity is an estimate; the threshold is a round number, not calibrated.",
                   *([VARIANT_NOTE] if variant_like else [])],
        ))
    findings += _location_templates(candidates, own_words, cfg, key_urls)
    summary = (f"{len(findings)} duplicate group(s) among {len(candidates)} indexable self-canonical page(s)." if findings
               else f"No duplicate groups among {len(candidates)} indexable self-canonical page(s).")
    if too_short:
        summary += (f" {len(too_short)} page(s) have fewer than {MIN_MAIN_WORDS_TO_COMPARE} words of their own and were "
                    "not compared for near-duplicates.")
    return CheckResult("IDX-8", title, _status(findings), summary, findings,
                       {"candidates": len(candidates), "near_duplicates_compared": MAIN_CONTENT_BASIS,
                        "site_wide_text_blocks_removed": len(repeated),
                        "too_little_main_content_to_compare": too_short[:40],
                        "too_little_main_content_to_compare_count": len(too_short)})


# -- IDX-9 -------------------------------------------------------------------

NOT_INDEXED_COVERAGE = ("crawled - currently not indexed", "discovered - currently not indexed")


def _norm_label(text: str | None) -> str:
    return (text or "").lower().replace("–", "-").replace("—", "-")


def idx9_google_index(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Google index status of key pages"
    data = _index(result)
    key_urls = key_page_urls(result, cfg)
    if not (cfg.gsc_access_token and cfg.gsc_site_url):
        return CheckResult("IDX-9", title, "not_assessed",
                           "Requires a Google Search Console connection (cost tier T2): an OAuth access token and the "
                           "property URL. None was provided.")
    if not key_urls:
        return CheckResult("IDX-9", title, "not_assessed", "No key pages are marked, and this check runs on key pages only.")
    gsc = data.gsc or {"results": []}
    by_url = {p.url: p for p in result.pages}
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    review, errors, passed, observations = [], [], [], []

    for entry in gsc["results"]:
        isr = entry.get("indexStatusResult")
        if not isr:
            errors.append({"url": entry["url"], "http_status": entry.get("http_status"), "error": entry.get("error")})
            continue
        row = {"url": entry["url"], "verdict": isr.get("verdict"), "coverageState": isr.get("coverageState"),
               "indexingState": isr.get("indexingState"), "robotsTxtState": isr.get("robotsTxtState"),
               "pageFetchState": isr.get("pageFetchState"), "lastCrawlTime": isr.get("lastCrawlTime"),
               "googleCanonical": isr.get("googleCanonical"), "userCanonical": isr.get("userCanonical")}
        coverage = _norm_label(isr.get("coverageState"))
        mapped = False
        if isr.get("indexingState") in ("BLOCKED_BY_META_TAG", "BLOCKED_BY_HTTP_HEADER"):
            groups[("S1", "Google reports the page excluded by noindex")].append(row)
            mapped = True
        elif any(label in coverage for label in NOT_INDEXED_COVERAGE):
            groups[("S1", f"Google reports: {isr.get('coverageState')}")].append(row)
            mapped = True
        elif isr.get("indexingState") == "BLOCKED_BY_ROBOTS_TXT" or isr.get("robotsTxtState") == "DISALLOWED":
            groups[("S1", "Google reports the page blocked by robots.txt")].append(row)
            mapped = True
        google, user = isr.get("googleCanonical"), isr.get("userCanonical")
        if google and user and google != user:
            groups[("S3", "Google chose a different canonical than the page declares")].append(row)
            mapped = True
        if isr.get("verdict") == "PASS" and not mapped:
            passed.append(row)
            page = by_url.get(entry["url"])
            if page and page.analysis:
                from ..directives import page_directives

                blocking = [d["raw"] for d in page_directives(page)
                            if d["directive"] in ("nosnippet", "none") or (d["directive"] == "max-snippet" and d["value"] == "0")]
                if blocking:
                    observations.append({"url": entry["url"], "metric": "indexed, but not eligible for a snippet "
                                         "(so not for AI Overviews); see ACC-3", "directives": blocking})
        elif not mapped:
            review.append(row)

    findings = []
    for (sev, label), rows in sorted(groups.items()):
        urls = [r["url"] for r in rows]
        notes = ["coverageState is free text in the API (not an enumerated value); labels are matched in English "
                 "(languageCode en-US)."]
        if "robots.txt" in label:
            notes.append("Same root cause as an ACC-2 finding when robots.txt disallows Googlebot for these URLs.")
        findings.append(Finding(
            "IDX-9", f"{label} ({len(urls)} key page(s))", Severity(sev), Confidence.VERIFIED, Rationale.DOCUMENTED.value,
            [GOOGLE], scope_for(urls), {"inspections": rows}, "key pages indexed and eligible for snippets in Google",
            "Resolve the reason Google gives (remove noindex, improve or consolidate the page, fix the canonical), then "
            "request reindexing in Search Console.",
            cost_tier="T2", notes=notes, importance_tier=0,
        ))
    review_items = []
    if review:
        urls = [r["url"] for r in review]
        review_items.append(ReviewItem(
            "IDX-9", f"Google reports a non-indexed state that has no severity rule ({len(urls)} key page(s))",
            "The URL Inspection result is not PASS and does not match a state the spec assigns a severity to (for "
            "example 'URL is unknown to Google'). A key page outside Google's index cannot appear in AI Overviews.",
            Confidence.VERIFIED, [GOOGLE], scope_for(urls), {"inspections": review},
            "Read the coverage state for each page and decide on the fix.", importance_tier=0,
        ))
    evidence = {"api": {k: v for k, v in gsc.items() if k != "results"}, "passed": passed, "errors": errors}
    if not findings and not review_items and not passed:
        return CheckResult("IDX-9", title, "not_assessed", f"All {len(errors)} inspection request(s) failed.",
                           evidence=evidence)
    summary = (f"{len(findings)} finding(s), {len(review_items)} review item(s); {len(passed)} key page(s) indexed."
               if findings or review_items else f"All {len(passed)} inspected key page(s) are indexed.")
    return CheckResult("IDX-9", title, _status(findings, review_items), summary, findings, evidence, observations, review_items)


# -- IDX-10 ------------------------------------------------------------------

def idx10_bing_index(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Bing index status of key pages"
    data = _index(result)
    findings, observations, review_items = [], [], []
    evidence: dict = {
        "index_status": "not assessed: Bing's documented UrlInfo object (GetUrlInfo) has no field that states "
                        "whether a URL is indexed, so 'not indexed' cannot be verified.",
    }
    if data.bing:
        evidence["api"] = {k: v for k, v in data.bing.items() if k != "results"}
        failing = []
        for entry in data.bing["results"]:
            info = entry.get("url_info")
            if not isinstance(info, dict):
                observations.append({"url": entry["url"], "metric": "GetUrlInfo failed", "http_status": entry.get("http_status")})
                continue
            observations.append({"url": entry["url"], "metric": "Bing crawl facts (GetUrlInfo)",
                                 **{k: info.get(k) for k in ("HttpStatus", "LastCrawledDate", "DiscoveryDate", "IsPage")}})
            status = info.get("HttpStatus")
            if isinstance(status, int) and status >= 400:
                failing.append({"url": entry["url"], "HttpStatus": status, "LastCrawledDate": info.get("LastCrawledDate")})
        if failing:
            urls = [f["url"] for f in failing]
            review_items.append(ReviewItem(
                "IDX-10", f"Bing's last crawl of {len(urls)} key page(s) got an HTTP error",
                "Bing recorded an error status on its last crawl. The spec's severity is for 'not indexed', which the "
                "API does not report, so this has no severity, but a key page Bing sees as an error is unlikely to be "
                "used by Copilot.",
                Confidence.VERIFIED, ["Microsoft Copilot (Bing index)"], scope_for(urls), {"pages": failing},
                "Check whether the page is healthy now (IDX-1) and resubmit it in Bing Webmaster Tools.",
                importance_tier=0,
            ))
    else:
        evidence["api"] = data.bing_skipped or "not connected (cost tier T2): no Bing Webmaster Tools API key and site URL provided"

    if data.indexnow:
        evidence["indexnow"] = data.indexnow
        if data.indexnow.get("checked") and not data.indexnow.get("key_matches"):
            findings.append(Finding(
                "IDX-10", f"IndexNow key file not found or not matching at {data.indexnow['key_location']}",
                Severity.INFO, Confidence.VERIFIED, "Documented (Copilot)", ["Microsoft Copilot (Bing index)"],
                scope_for([data.indexnow["key_location"]], sitewide=True), data.indexnow,
                "the IndexNow key file is published at its key location",
                "Publish the key file containing the key, or correct the key location.",
            ))
    else:
        evidence["indexnow"] = "not verified: no IndexNow key or key location provided"

    connected = data.bing is not None or (data.indexnow or {}).get("checked")
    if not connected:
        return CheckResult("IDX-10", title, "not_assessed",
                           (f"Bing lookups not run: {data.bing_skipped} " if data.bing_skipped else
                            "Requires a Bing Webmaster Tools API key (T2) or an IndexNow key location; neither was provided. ")
                           + "Index status itself cannot be verified from Bing's documented API.", evidence=evidence)
    summary = ("Index status not assessed (not exposed by Bing's documented API); "
               f"{len(findings)} finding(s), {len(review_items)} review item(s), {len(observations)} observation(s).")
    return CheckResult("IDX-10", title, _status(findings, review_items), summary, findings, evidence, observations, review_items)


def run_index_checks(result: CrawlResult, cfg: CrawlConfig) -> list[CheckResult]:
    checks = [
        idx1_http_status(result, cfg),
        idx2_tls(result, cfg),
        idx3_redirects(result, cfg),
        idx4_canonicals(result, cfg),
        idx5_sitemap(result, cfg),
        idx6_broken_links(result, cfg),
        idx7_discoverability(result, cfg),
        idx8_duplicates(result, cfg),
        idx9_google_index(result, cfg),
        idx10_bing_index(result, cfg),
    ]
    from .quick_rules import extend  # the checklist's quick checks (DECISIONS 304): IDX-5, IDX-6, IDX-7
    extend(checks, result, cfg)
    return settle_all(checks, result)


BROKEN_LINK_NOTE = ("The affected addresses are the pages whose links lead to an error, and the sitemap entries that "
                    "end at one; the failing addresses themselves are listed apart (evidence.target_urls).")


# DECISIONS 338: HSTS of at least a year on the https:// homepage makes a temporary http:// -> https:// code hygiene.
HSTS_LONG_S = 31_536_000
HSTS_NOTE = ("Info, not a problem: the https:// pages send HSTS for {days} days, so browsers do not ask http:// at all, and "
             "the redirect goes to the https:// address. A permanent code (301 or 308) is still the clean choice.")


def hsts_max_age(result) -> int | None:
    """The HSTS max-age (seconds) the https:// homepage sent, or None."""
    try:
        home = homepage_url(result)
    except Exception:  # a saved crawl without what the homepage needs
        home = None
    for p in getattr(result, "pages", None) or []:
        if p.url == home or (p.depth == 0 and str(p.url).startswith("https://")):
            value = {str(k).lower(): v for k, v in (p.headers or {}).items()}.get("strict-transport-security") or ""
            m = re.search(r"max-age\s*=\s*\"?(\d+)", value, re.I)
            if m:
                return int(m.group(1))
    return None


# DECISIONS 337: the 4xx addresses only a sitemap lists, and real links whose written address is mistyped, are cards of
# their own: their fix is the sitemap (or its generator) and the href, not "the links to an error page".
SITEMAP_ONLY_4XX_TITLE = "{n} sitemap address(es) end at a client error (4xx); no page read links to them"
SITEMAP_ONLY_EXPECTED = "the sitemap lists only addresses that answer 200"
SITEMAP_ONLY_FIX = ("Take these entries out of the sitemap, or redirect each one that once held content to its closest page. "
                    "When they come from page headings or FAQ questions, fix the sitemap generator so it lists pages only.")
SITEMAP_ONLY_NOTE = ("No page Maya read links to these addresses: they are in the sitemap only. Maya reads a sample, so a "
                     "page it did not read may still link to one.")
FROM_HEADINGS_NOTE = ("Inference: {n} of these addresses spell a heading or FAQ question on a page Maya read (evidence."
                      "likely_cause): the sitemap generator seems to make addresses from headings. Check it.")
MISTYPED_TITLE = "{links} link(s) on {pages} page(s) have a mistyped address (href) that ends at a client error (4xx)"
MISTYPED_EXPECTED = "every link's href is the address it means: a path starting with /, a full address or #section"
MISTYPED_FIX = ("Correct the href in the page or template that holds it (evidence gives the value as written): add the "
                "missing / or #, or put the address in place of the text.")


def _key_urls(result) -> set[str]:
    cfg = getattr(result, "config", None)
    pages = cfg.get("key_pages") if isinstance(cfg, dict) else getattr(cfg, "key_pages", None)
    origin = getattr(result, "origin", "") or ""
    keys = {normalize_url(k, origin) for k in pages or []}
    try:
        keys.add(homepage_url(result))
    except Exception:  # a saved crawl without what the homepage needs
        pass
    return {k for k in keys if k}


def link_inbound(result) -> dict[str, list[dict]]:
    """{address: every link or redirect that reaches it}: the page, its link text, the href as written, whether the link
    sits in the menu or the footer; a redirect is {"anchor": "(redirect)"} (DECISIONS 278, 337)."""
    inbound: dict[str, list[dict]] = defaultdict(list)
    for page in result.pages:
        for edge in page.outlinks or []:
            inbound[edge["target"]].append({"source": page.url, "anchor": edge.get("anchor") or "", "href": edge.get("href"),
                                            "nav": bool(edge.get("nav")), "footer": bool(edge.get("footer"))})
        if page.redirect_location:
            inbound[page.redirect_location].append({"source": page.url, "anchor": "(redirect)"})
    return inbound


def trace_to_links(targets, inbound, listed) -> tuple[list[dict], list[str]]:
    """(one row per link that ends at a target, the listed addresses that end there with no link): each target is traced
    back through the crawl's redirects to the links and sitemap entries that reach it."""
    rows, in_sitemap = [], []
    for target in targets:
        frontier, seen = [target], {target}
        while frontier:
            url = frontier.pop()
            if url in listed:
                in_sitemap.append(url)
            for ref in inbound.get(url, []):
                if ref["anchor"] == "(redirect)":
                    if ref["source"] not in seen:
                        seen.add(ref["source"])
                        frontier.append(ref["source"])
                else:
                    rows.append({"source": ref["source"], "anchor": ref["anchor"], "links_to": url, "target": target,
                                 "href": ref.get("href"),
                                 "position": "menu" if ref.get("nav") else "footer" if ref.get("footer") else "body"})
    sources = {row["source"] for row in rows}
    linked_to = {row["links_to"] for row in rows}
    return rows, [u for u in dict.fromkeys(in_sitemap) if u not in sources and u not in linked_to]


_FOLD = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def _heading_words(text: str) -> str:
    """A heading or an address part as plain words: lower case, Turkish letters folded ("kartı" and "karti" agree)."""
    from urllib.parse import unquote
    text = unquote(text or "").replace("İ", "i").replace("I", "ı").lower().translate(_FOLD)
    return " ".join(re.findall(r"[0-9a-z]+", text))


def heading_matches(addresses, pages) -> dict[str, dict]:
    """{address: {page, heading, level}} for a sitemap address whose last part spells a heading on a page read (a
    trailing copy number such as "...acabilirim2" left out). Evidence for an inference, never a finding by itself."""
    headings: dict[str, dict] = {}
    for page in pages:
        for h in ((getattr(page, "analysis", None) or {}).get("headings") or []):
            text = h.get("text") if isinstance(h, dict) else None
            key = _heading_words(text or "")
            if key and len(key) >= 8 and key not in headings:
                headings[key] = {"page": page.url, "heading": text, "level": h.get("level")}
    out = {}
    for url in addresses:
        last = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
        for key in (_heading_words(last), re.sub(r"\d+$", "", _heading_words(last)).strip()):
            if key in headings:
                out[url] = headings[key]
                break
    return out


def broken_link_sources(checks, result: CrawlResult) -> None:
    """IDX-1's "4xx, linked internally or listed in the sitemap" finding names the pages to edit (DECISIONS 278), split
    by what is to be fixed (DECISIONS 337).

    The 4xx address is often the site's own error page, reached through a redirect. Each 4xx target is traced back
    through the crawl's redirects to the HTML pages whose links lead to it and to the sitemap entries that end there:
    - links whose written address looks mistyped (`html_links.mistyped_href`: spaces, no leading slash) become
      "N link(s) ... have a mistyped address (href)", Low, Medium when a key page or the homepage holds one;
    - the other links stay "... linked internally or listed in the sitemap; linked from N page(s)";
    - addresses only a sitemap lists become "N sitemap address(es) end at a client error (4xx)", with the file that
      lists each one and, when its words spell a heading on a page read, that heading (an inference).
    The linked and sitemap findings keep the engine's severity. `evidence.target_urls` keeps the 4xx addresses,
    `evidence.link_sources` one row per link. Runs after severities are set; a finding already split is left alone.
    """
    from dataclasses import replace
    from ..html_links import mistyped_href
    from ..sitemap import file_map
    check = next((c for c in checks if c.check_id == "IDX-1"), None)
    if check is None:
        return
    inbound = link_inbound(result)
    listed = set(result.sitemap_urls or [])
    statuses = {p.url: p.status for p in result.pages}
    added: list[Finding] = []
    for finding in check.findings:
        if not REFERENCED_4XX_TITLE.search(finding.title) or finding.evidence.get("split") == 337:
            continue
        targets = list(finding.evidence.get("target_urls") or finding.scope.get("_all_urls") or finding.scope.get("urls") or [])
        if not targets:
            continue
        rows, sitemap_only = trace_to_links(targets, inbound, listed)
        mistyped = [r for r in rows if mistyped_href(r.get("href"))]
        for r in mistyped:
            r["mistyped"] = mistyped_href(r.get("href"))
        linked = [r for r in rows if not r.get("mistyped")]
        pages = finding.evidence.get("pages") or []
        base_ev = {k: v for k, v in finding.evidence.items() if k not in ("target_urls", "target_count", "link_sources",
                                                                           "link_sources_count", "sitemap_only", "pages")}

        def pages_for(ts, pages=pages):
            return [p for p in pages if p.get("url") in ts] or pages[:0]

        def make(title, scope_urls, ts, link_rows, only, extra=None, **change):
            new = replace(finding, title=title, scope=scope_for(scope_urls), id="", rule_id=None, notes=list(change.pop("notes", finding.notes)),
                          evidence={**base_ev, "pages": pages_for(set(ts)), "target_urls": ts[:40], "target_count": len(ts),
                                    "link_sources": link_rows[:40], "link_sources_count": len(link_rows),
                                    "sitemap_only": only[:40], "split": 337, **(extra or {})}, **change)
            new.__post_init__()
            return new

        out: list[Finding] = []
        if linked:
            sources = list(dict.fromkeys(r["source"] for r in linked))
            ts = list(dict.fromkeys(r["target"] for r in linked))
            title = re.sub(r"^\d+", str(len(ts)), re.sub(r"; linked from \d+ page\(s\)$", "", finding.title))
            out.append(make(title + IDX6_SUFFIX.format(pages=len(sources)), sources, ts, linked, [],
                            notes=[*finding.notes, BROKEN_LINK_NOTE]))
        if sitemap_only:
            files = file_map(getattr(result, "sitemap_docs", None), result.sitemap_urls, getattr(result, "_sitemap_file_of", None))
            matches = heading_matches(sitemap_only, result.pages)
            locs = getattr(result, "_sitemap_loc_of", None) or {}
            read_at = getattr(result, "_sitemap_read_at", None) or {}
            ends = {}
            for url in sitemap_only:
                hop = url
                for _ in range(10):
                    nxt = next((p.redirect_location for p in result.pages if p.url == hop and p.redirect_location), None)
                    if not nxt:
                        break
                    hop = nxt
                ends[url] = hop
            entries = [{"url": u, "ends_at": ends[u], "status": statuses.get(ends[u]), "first_status": statuses.get(u),
                        "sitemap_file": files.get(u), "heading_match": matches.get(u),
                        # DECISIONS 340: the <loc> as the file writes it, its line, and when the file was read
                        **({"sitemap_loc": locs[u]["loc"], "sitemap_line": locs[u]["line"]} if u in locs else {}),
                        **({"sitemap_read_at": read_at[files[u]]} if files.get(u) in read_at else {}),
                        "suggested": "fix_generator" if u in matches else "remove_or_redirect"} for u in sitemap_only]
            ts = list(dict.fromkeys(e["ends_at"] for e in entries))
            notes = [SITEMAP_ONLY_NOTE] + ([FROM_HEADINGS_NOTE.format(n=len(matches))] if matches else [])
            out.append(make(SITEMAP_ONLY_4XX_TITLE.format(n=len(sitemap_only)), sitemap_only, ts, [], sitemap_only,
                            {"sitemap_entries": entries[:60],
                             "sitemap_files": dict(sorted(Counter_(files.get(u) or "" for u in sitemap_only).items())),
                             "likely_cause": ({"kind": "from_headings", "inference": True, "count": len(matches)} if matches else None)},
                            notes=notes, expected=SITEMAP_ONLY_EXPECTED, how_to_fix=SITEMAP_ONLY_FIX))
        if mistyped:
            sources = list(dict.fromkeys(r["source"] for r in mistyped))
            ts = list(dict.fromkeys(r["target"] for r in mistyped))
            on_key = bool(set(sources) & _key_urls(result))
            out.append(make(MISTYPED_TITLE.format(links=len(mistyped), pages=len(sources)), sources, ts, mistyped, [],
                            notes=[BROKEN_LINK_NOTE], severity=Severity.S3 if on_key else Severity.S4,
                            expected=MISTYPED_EXPECTED, how_to_fix=MISTYPED_FIX, importance_tier=0 if on_key else 2))
        if not out:  # nothing traced (no link, no sitemap entry): the finding stays as it was, marked
            finding.evidence = {**finding.evidence, "target_urls": targets[:40], "target_count": len(targets),
                                "link_sources": [], "link_sources_count": 0, "sitemap_only": [], "split": 337}
            continue
        first, rest = out[0], out[1:]
        finding.title, finding.scope, finding.evidence, finding.notes = first.title, first.scope, first.evidence, first.notes
        finding.severity, finding.expected, finding.how_to_fix = first.severity, first.expected, first.how_to_fix
        finding.importance_tier, finding.id, finding.rule_id = first.importance_tier, "", None
        finding.__post_init__()
        added += rest
    check.findings.extend(added)
