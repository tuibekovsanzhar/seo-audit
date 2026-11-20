"""Requests made after the crawl for the ACC checks, through the same fetcher.

Order: robots.txt re-samples (ACC-1; scheduled, and sent by the fetcher once due, DECISIONS 219), ownership
verification (no request),
tagged probes on verified sites (ACC-4) or, without ownership, the smaller
browser/Googlebot check (ACC-4, DECISIONS 205), llms.txt (ACC-8), then local
log analysis (ACC-5). All of it is audited by INT-4.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .config import CrawlConfig
from .fetcher import Fetcher, utc_now
from .html_links import decode_body
from .logs import analyze_logs
from .models import CrawlResult, FetchClass, StopReason
from .probes import run_probes, run_ua_check
from .robots import looks_like_html
from .urls import detect_templates, normalize_url, same_origin
from . import clock as _clock

MAX_REDIRECTS = 5
LLMS_PATHS = ("/llms.txt", "/llms-full.txt")
# llms.txt and llms-full.txt are read whole up to this size (DECISIONS 208).
LLMS_MAX_BYTES = 1024 * 1024
_MARKDOWN_LINK = re.compile(r"\[([^\]\n]{0,300})\]\(\s*<?([^()\s<>]+(?:\([^()\s]*\)[^()\s<>]*)*)>?(?:\s+\"[^\"]*\")?\s*\)")
# P3: an address written bare ("* https://…") or as an autolink (<https://…>) in llms.txt; not one inside a word or
# another address, and without the ")" of surrounding prose. Code spans are left out (an example, not a link).
_BARE_URL = re.compile(r"(?<![\w/@.\-])https?://[^\s<>\"'`\]\[)(]+")
_CODE_SPAN = re.compile(r"`[^`\n]*`")
# What a link of llms.txt that does not work leads to (ACC-8): the words the finding uses for each kind.
LLMS_BAD_KINDS = {"empty": "empty page", "redirect": "redirect", "not_found": "not found", "server_error": "server error"}


@dataclass
class AccessData:
    origin: str
    robots_samples: list[dict[str, Any]]
    ownership: dict[str, Any]
    url_sample: list[dict[str, Any]]
    probe_sample: list[str]
    probes: dict[str, Any] | None
    probes_skipped_reason: str | None
    llms: list[dict[str, Any]]
    logs: dict[str, Any] | None
    notes: list[str] = field(default_factory=list)
    # ACC-4 without ownership: a browser and Googlebot's user agent, one request each (DECISIONS 205).
    ua_check: dict[str, Any] | None = None


def key_page_urls(result: CrawlResult, cfg: CrawlConfig) -> list[str]:
    urls = [normalize_url(k, result.origin) for k in cfg.key_pages]
    return [u for u in urls if u]


def homepage_url(result: CrawlResult) -> str:
    """The start URL, or where its redirect chain landed. When the start address gave no readable page (a 404, a
    redirect that never ended) and the site's root was read, the root: the homepage is then the page the audit really
    has, not the address that failed (DECISIONS 199). A deep start address that answers 200 stays the page audited."""
    landed = [p for p in result.pages if p.depth == 0 and p.status and 200 <= p.status < 300]
    if landed:
        return landed[0].url
    root = f"{getattr(result, 'origin', None) or ''}/"
    if any(p.url == root and p.status and 200 <= p.status < 300 for p in result.pages):
        return root
    return result.start_url


def build_url_sample(result: CrawlResult, cfg: CrawlConfig) -> list[dict[str, Any]]:
    """ACC-2 sample: homepage, key pages, one URL per template, sitemap sample."""
    reasons: dict[str, list[str]] = {}

    def add(url: str | None, why: str) -> None:
        if url and same_origin(url, result.origin):
            reasons.setdefault(url, []).append(why)

    add(homepage_url(result), "homepage")
    for url in key_page_urls(result, cfg):
        add(url, "key page")
    for template, urls in sorted(detect_templates(result.discovered_urls).items()):
        add(sorted(urls)[0], f"template {template}")
    for url in result.sitemap_urls[:10]:
        add(url, "sitemap sample")
    return [{"url": url, "why": why} for url, why in list(reasons.items())[: cfg.url_sample_size]]


def build_probe_sample(result: CrawlResult, cfg: CrawlConfig) -> list[str]:
    """ACC-4 sample: homepage, robots.txt, sitemap, key pages, one fetched page per template."""
    readable = {
        p.url for p in result.pages
        if p.fetch_class == FetchClass.OK and p.status is not None and 200 <= p.status < 300
    }
    ordered: list[str] = [homepage_url(result), f"{result.origin}/robots.txt"]
    ordered += [d.url for d in result.sitemap_docs if d.status == 200][:1]
    ordered += [u for u in key_page_urls(result, cfg) if u in readable]
    ordered += [sorted(urls)[0] for _, urls in sorted(detect_templates(sorted(readable)).items())]
    return list(dict.fromkeys(ordered))[: cfg.probe_sample_size]


def build_ua_check_sample(result: CrawlResult, cfg: CrawlConfig) -> list[str]:
    """ACC-4 without ownership (DECISIONS 205, 216): the homepage, then the pages of the largest page template in order
    (then the next template's), at most `ua_check_urls`. An empty page (IDX-1) is not picked: a browser gets nothing
    there either, so it shows no difference made for Googlebot."""
    answered = [p for p in result.pages if p.fetch_class == FetchClass.OK and p.status is not None and 200 <= p.status < 300
                and same_origin(p.url, result.origin) and not (p.analysis or {}).get("empty_response")]
    home = homepage_url(result)
    ordered: list[str] = [home]
    # DECISIONS 374: one page whose robots tag sits outside <head>, so the Googlebot request shows where Googlebot gets it
    stray = sorted(p.url for p in answered if p.url != home and ((p.analysis or {}).get("outside_head") or {}).get("robots_content"))
    if stray and cfg.ua_check_urls > 1:
        ordered.append(stray[0])
    templates = sorted(detect_templates([p.url for p in answered if p.url != home]).items(), key=lambda kv: (-len(kv[1]), kv[0]))
    for _, urls in templates:
        for url in sorted(urls):
            if len(ordered) >= cfg.ua_check_urls:
                break
            if url not in ordered:
                ordered.append(url)
    return list(dict.fromkeys(ordered))[: cfg.ua_check_urls]


def verify_ownership(result: CrawlResult, cfg: CrawlConfig) -> dict[str, Any]:
    """The meta tag <meta name="maya-site-verification" content="TOKEN"> on the homepage, or, when switched on, the
    same token in the domain's DNS TXT record (maya_audit.ownership). The Search Console method is not built.
    """
    base = {"method": "meta_tag", "meta_name": "maya-site-verification", "methods_not_built": ["search_console"]}
    if not cfg.site_verification_token:
        return {**base, "verified": False, "reason": "no site verification token configured"}
    found = _meta_tag_ownership(result, cfg, base)
    if found["verified"] or not cfg.site_verification_dns:
        return found
    from . import ownership
    from .urls import registrable_domain

    domain = registrable_domain(urlsplit(result.origin).hostname or "")
    by_dns = ownership.dns_txt_verified(domain, cfg.site_verification_token)
    if by_dns["verified"]:
        return {**base, **by_dns, "checked_at": utc_now(), "meta_tag": found["reason"]}
    return {**found, "dns_txt": by_dns["reason"], "reason": f"{found['reason']}; {by_dns['reason']}"}


def _meta_tag_ownership(result: CrawlResult, cfg: CrawlConfig, base: dict[str, Any]) -> dict[str, Any]:
    for page in result.pages:
        if page.depth == 0 and page.analysis is not None:
            tokens = page.analysis["verification_tokens"]
            if cfg.site_verification_token in tokens:
                return {**base, "verified": True, "page": page.url, "checked_at": page.requested_at,
                        "reason": "verification meta tag on the homepage matches the configured token"}
            return {**base, "verified": False, "page": page.url, "meta_tags_found": len(tokens),
                    "reason": "homepage has no verification meta tag matching the configured token"}
    return {**base, "verified": False, "reason": "homepage could not be read, so the meta tag could not be checked"}


def _fetch_robots_sample(fetcher: Fetcher, origin: str, cfg: CrawlConfig, attempt: int) -> dict[str, Any]:
    url = f"{origin}/robots.txt"
    hops: list[str] = []
    response = fetcher.get(url, "robots_sample", cfg.max_robots_bytes + 1)
    while (
        response.error is None and response.status is not None and 300 <= response.status < 400
        and response.headers.get("location") and len(hops) < MAX_REDIRECTS
    ):
        target = normalize_url(response.headers["location"], response.url)
        if target is None:
            break
        hops.append(target)
        response = fetcher.get(target, "robots_sample", cfg.max_robots_bytes + 1)
    content_type = response.headers.get("content-type")
    return {
        "attempt": attempt,
        "url": url,
        "requested_at": response.started_at,
        "status": response.status,
        "error": response.error,
        "content_type": content_type,
        "bytes": len(response.body),
        "over_500_kib": len(response.body) > cfg.max_robots_bytes,
        "looks_like_html": looks_like_html(response.body, content_type),
        "redirect_hops": hops,
        "user_agent": fetcher.user_agent,
    }


def first_line(text: str) -> str:
    """The first line of `text` that holds anything but spaces, without its line break ("" for an empty file)."""
    return next((line.strip() for line in text.lstrip("\ufeff").splitlines() if line.strip()), "")


def llms_links(text: str, base: str) -> list[dict[str, str]]:
    """The links of an llms.txt file, each address made absolute, in the file's order, once each: Markdown links
    [text](url) first, then (P3) addresses written bare or as <url>, outside Markdown links and code spans. Seen live:
    a file listing its pages as "* https://…" was read as having no links at all."""
    out: dict[str, dict[str, str]] = {}
    for found in _MARKDOWN_LINK.finditer(text):
        url = normalize_url(found.group(2), base)
        if url and url not in out:
            out[url] = {"text": " ".join(found.group(1).split())[:120], "url": url}
    rest = _CODE_SPAN.sub(lambda m: " " * len(m.group(0)), _MARKDOWN_LINK.sub(lambda m: " " * len(m.group(0)), text))
    for line in rest.splitlines():
        for found in _BARE_URL.finditer(line):
            url = normalize_url(found.group(0).rstrip(".,;:!?"), base)
            if url and url not in out:
                label = (line[:found.start()] + line[found.end():]).strip(" \t*-+<>:–—")
                out[url] = {"text": " ".join(label.split())[:120], "url": url}
    return list(out.values())


def _link_counts(links: list[dict[str, str]], origin: str) -> dict[str, Any]:
    same = sum(1 for link in links if same_origin(link["url"], origin))
    return {"found": len(links), "same_site": same, "other_site": len(links) - same, "checked": 0, "not_working": 0,
            "kinds": {}, "not_checked": {}, "rows": []}


def ask_llms_links_on_site(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig, sitemap_check=None,
                           state: dict | None = None) -> dict:
    """DECISIONS 330: the light requests `check_llms_links` would send for llms.txt's links to this site, asked early on
    a lane of their own (beside index, structure and rendering), in the same order, with the same cap, robots.txt rules
    and stopping rules. Their answers and the stop state go in `state`, which `check_llms_links` then reuses: it sends
    nothing again for these links, and asks only the links to other sites (after the other-site pool, as before)."""
    from .index_data import LightRequests, _NO_MORE_REQUESTS
    state = state if state is not None else {}
    access = result.access
    if access is None or cfg.single_page:
        return state
    policy = result.robots_policy_by_origin.get(result.origin)
    if result.stop_reason in _NO_MORE_REQUESTS or policy is None or policy.stops_requests:
        return state
    asked = state.setdefault("asked", {})
    requests = state.setdefault("requests", LightRequests(fetcher, cfg, policy, "llms_link_check"))
    crawl = {p.url for p in result.pages}
    light = {row["url"] for row in (getattr(sitemap_check, "rows", None) or [])}
    for entry in access.llms:
        for link in entry.get("_links") or []:
            url = link["url"]
            if not same_origin(url, result.origin) or url in crawl or url in light or url in asked:
                continue
            if (not policy.decide(cfg.product_token, url).allowed or len(asked) >= cfg.llms_link_checks_max
                    or requests.stopped_because):
                continue
            fresh = requests.ask(url)
            if fresh is not None:
                asked[url] = fresh
    return state


def check_llms_links(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig, sitemap_check=None,
                     state: dict | None = None) -> None:
    """ACC-8 (DECISIONS 208): where each link of llms.txt to this site leads. Judged from the crawl, then from the
    sitemap check's light requests; any other is asked with the same light request, at most `llms_link_checks_max`
    in all, robots.txt obeyed, stopping on a 429, 3 blocked answers in a row or the time limit. A link to another
    site goes through the other-site check (maya_audit.external_links, DECISIONS 211): one HEAD request within its
    cap, 404 or 410 counting as not found and a redirect as working. Fills `links` of each entry of
    `result.access.llms` in place."""
    from . import external_links as external
    from .index_data import LightRequests, _NO_MORE_REQUESTS, page_kind, row_kind
    from .urls import registrable_domain

    access = result.access
    if access is None:
        return
    policy = result.robots_policy_by_origin.get(result.origin)
    crawl = {p.url: p for p in result.pages}
    light = {row["url"]: row for row in (getattr(sitemap_check, "rows", None) or [])}
    why_none = ("single_page" if cfg.single_page else "crawl_stopped" if result.stop_reason in _NO_MORE_REQUESTS
                else "robots_unreadable" if policy is None or policy.stops_requests else None)
    # DECISIONS 330: what `ask_llms_links_on_site` already asked (and its stop state) is reused, never sent again.
    state = state if state is not None else {}
    requests = state.get("requests") or LightRequests(fetcher, cfg, policy, "llms_link_check")
    asked: dict[str, dict[str, Any]] = state.get("asked") or {}
    for entry in access.llms:
        links = entry.get("_links") or []
        counts = entry.get("links") or _link_counts(links, result.origin)
        if cfg.single_page:  # presence and the first line only: no link is asked for or judged
            entry["links"] = {**counts, "single_page": True}
            continue
        rows, not_checked = [], {}
        site = registrable_domain(urlsplit(result.origin).hostname or "")
        for link in links:
            url = link["url"]
            if not same_origin(url, result.origin):
                if not external.other_site(url, result.origin, site, cfg.brand_family_domains):
                    not_checked["own_host"] = not_checked.get("own_host", 0) + 1
                    continue
                found = external.check(fetcher, result, cfg, url)
                if not found["checked"]:
                    key = f"external_{found['verdict']}"
                    not_checked[key] = not_checked.get(key, 0) + 1
                    continue
                broken = found["verdict"] == "broken"
                rows.append({"text": link["text"], "url": url, "source": "other site (one HEAD request)",
                             "status": found.get("status"), "location": found.get("location"),
                             "kind": "not_found" if broken else "live", "works": not broken})
                continue
            if url in crawl:
                kind, row, source = page_kind(crawl[url]), {"status": crawl[url].status, "location": crawl[url].redirect_location}, "crawl"
            elif url in light:
                kind, row, source = row_kind(light[url]), light[url], "sitemap check"
            elif url in asked:
                kind, row, source = row_kind(asked[url]), asked[url], "light request"
            else:
                reason = (why_none or ("robots" if not policy.decide(cfg.product_token, url).allowed else None)
                          or ("cap" if len(asked) >= cfg.llms_link_checks_max else None) or requests.stopped_because)
                fresh = None if reason else requests.ask(url)
                if fresh is None:
                    reason = reason or requests.stopped_because or "time_limit"
                    reason = "blocked_in_a_row" if reason == "blocked" else reason
                    not_checked[reason] = not_checked.get(reason, 0) + 1
                    continue
                asked[url] = fresh
                kind, row, source = row_kind(fresh), fresh, "light request"
            if kind in ("blocked", "no_answer"):
                kind = "blocked_answer" if kind == "blocked" else kind
                not_checked[kind] = not_checked.get(kind, 0) + 1
                continue
            rows.append({"text": link["text"], "url": url, "source": source, "status": row.get("status"),
                         "location": row.get("location"), "kind": kind,
                         "works": kind not in LLMS_BAD_KINDS})
        # A redirect is an observation, not a broken link. Reuse only already guarded observations;
        # do not make new requests, bypass robots, or silently increase the link-check budget.
        observed = {**light, **asked}
        observed.update({u: {"status": p.status, "location": p.redirect_location, "kind": page_kind(p)}
                         for u, p in crawl.items()})
        for item in rows:
            if item["kind"] != "redirect":
                continue
            # The file names an address that moves (B15): said apart, whether or not the destination works.
            item["redirected"] = True
            destination = normalize_url(item.get("location") or "", item["url"])
            visited = {item["url"]}
            trail = []
            while destination and destination not in visited and same_origin(destination, result.origin):
                if policy is None or not policy.decide(cfg.product_token, destination).allowed:
                    break
                visited.add(destination)
                next_row = observed.get(destination)
                if next_row is None:
                    break
                kind = next_row.get("kind") or row_kind(next_row)
                trail.append({"url": destination, "status": next_row.get("status"), "kind": kind})
                if kind == "redirect":
                    destination = normalize_url(next_row.get("location") or "", destination)
                    continue
                if kind in ("live", "noindex", "empty", "not_found", "server_error"):
                    item.update(kind=kind, works=kind not in LLMS_BAD_KINDS,
                                final_url=destination, redirect_evidence=trail)
                break
            if item["kind"] == "redirect":
                item.update(works=None, redirect_evidence=trail,
                            qualification="redirect destination not established by comparable saved requests")
                not_checked["redirect_destination_unassessed"] = not_checked.get("redirect_destination_unassessed", 0) + 1
        bad = [r for r in rows if r["works"] is False]
        kinds: dict[str, int] = {}
        for r in bad:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        counts.update(checked=sum(r["works"] is not None for r in rows), not_working=len(bad), kinds=kinds, not_checked=not_checked,
                      not_working_urls=[r["url"] for r in bad],
                      redirecting=[{"url": r["url"], "final_url": r.get("final_url"), "location": r.get("location")}
                                   for r in rows if r.get("redirected")][:40],
                      rows=(bad + [r for r in rows if r["works"] is not False])[:40],
                      single_page=bool(cfg.single_page))
        entry["links"] = counts
    if sitemap_check is not None:
        sitemap_check.llms_rows = list(asked.values())


def collect_access_data(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig) -> AccessData:
    origin = result.origin
    policy = result.robots_policy_by_origin[origin]

    # ACC-1: the crawl's own robots.txt fetch is sample 1; take the rest spaced out.
    first = next(p for p in result.robots if p["url"] == f"{origin}/robots.txt")
    samples = [{
        "attempt": 1, "url": first["url"], "requested_at": policy.fetched_at, "status": first["status"],
        "error": first["error"], "content_type": first["content_type"],
        "bytes": first["bytes_read"] + (1 if first["truncated"] else 0),
        "over_500_kib": first["truncated"], "looks_like_html": first["looks_like_html"],
        "redirect_hops": first["redirect_hops"], "user_agent": fetcher.user_agent,
    }]
    # The later samples are not waited for here (DECISIONS 219; decision 12's 3 samples at least the interval apart stay):
    # the fetcher sends each once it has come due, before its next request, and waits only for one still not due when
    # Maya's last step ends. Each is due the interval after the one before it was sent.
    first_sent = next((r.started_mono for r in fetcher.log if r.purpose == "robots" and r.url == first["url"]
                       and r.started_mono is not None), None)

    def take(attempt: int) -> None:
        before = len(fetcher.log)
        sample = _fetch_robots_sample(fetcher, origin, cfg, attempt)
        if sample["error"] == "audit_deadline_skipped":
            return  # never sent: the time limit came first
        samples.append(sample)
        if attempt < cfg.robots_samples:
            # The sample's own record: since DECISIONS 328 the sitemap check's thread writes to the log beside it, so the
            # record after `before` may be another step's request (the next sample was then due too early).
            own = [r for r in fetcher.log[before:] if r.purpose == "robots_sample" and r.started_mono is not None]
            sent = own[0].started_mono if own else _clock.monotonic()
            fetcher.schedule(sent + cfg.robots_sample_interval_s, lambda: take(attempt + 1))

    if cfg.robots_samples >= 2:
        fetcher.schedule((first_sent if first_sent is not None else _clock.monotonic()) + cfg.robots_sample_interval_s,
                         lambda: take(2))

    ownership = verify_ownership(result, cfg)
    url_sample = build_url_sample(result, cfg)
    probe_sample = build_probe_sample(result, cfg)

    probes, skipped_reason, ua_check = None, None, None
    if not ownership["verified"]:
        skipped_reason = f"ownership not verified ({ownership['reason']})"
        # The smaller check that needs no ownership: a browser and Googlebot's user agent, tagged, once each.
        # Not after a crawl the site rate-limited: it has already asked Maya to stop.
        if (cfg.probes_enabled and cfg.ua_check_urls > 0 and not policy.stops_requests
                and result.stop_reason != StopReason.RATE_LIMIT):
            ua_check = run_ua_check(fetcher, cfg, build_ua_check_sample(result, cfg), policy)
    elif not cfg.probes_enabled:
        skipped_reason = "probes disabled in configuration"
    elif policy.stops_requests:
        skipped_reason = ("robots.txt was not checked: Maya makes no further requests to this site" if policy.mode == "not_checked"
                          else "robots.txt unavailable: Maya makes no further requests to this site")
    else:
        probes = run_probes(fetcher, cfg, probe_sample)

    llms = []
    for path in LLMS_PATHS:
        url = origin + path
        decision = policy.decide(cfg.product_token, url)
        if not decision.allowed:
            llms.append({"url": url, "fetched": False, "reason": decision.reason})
            continue
        response = fetcher.get(url, "llms", LLMS_MAX_BYTES)
        # One redirect is followed (B15): a file moved with a 301 is still the site's llms.txt. Only on this site and
        # where robots.txt allows the destination; a second redirect is recorded, not followed.
        redirected_to = None
        if response.error is None and response.status is not None and 300 <= response.status < 400 and response.headers.get("location"):
            target = normalize_url(response.headers["location"], url)
            redirected_to = target
            if target and same_origin(target, origin) and policy.decide(cfg.product_token, target).allowed:
                response = fetcher.get(target, "llms", LLMS_MAX_BYTES)
        content_type = response.headers.get("content-type")
        text = decode_body(response.body, content_type) if response.body else ""
        # Present means a text file: a 200 that is an HTML page (a soft 404, the homepage) is not llms.txt (B15).
        readable = response.status == 200 and bool(text.strip()) and not looks_like_html(response.body, content_type)
        links = llms_links(text, redirected_to or url) if readable else []
        llms.append({
            "url": url,
            "fetched": True,
            "requested_at": response.started_at,
            "status": response.status,
            "readable": readable,
            "redirected_to": redirected_to,
            "error": response.error,
            "content_type": content_type,
            "bytes": len(response.body),
            "bom": response.body.startswith(b"\xef\xbb\xbf"),  # DECISIONS 363: a UTF-8 byte-order mark first
            # Estimated: llms.txt files conventionally open with a Markdown H1.
            "looks_like_markdown": bool(readable and text.lstrip().startswith("# ")),
            # ACC-8 (DECISIONS 208): the first line that holds anything, and the Markdown links [text](url) of the file.
            "first_line": first_line(text)[:200] if readable else None,
            "links": _link_counts(links, origin),
            "_links": links,
        })

    logs = analyze_logs(cfg.access_logs, cfg.access_log_format, cfg.ip_range_files) if cfg.access_logs else None

    return AccessData(origin, samples, ownership, url_sample, probe_sample, probes, skipped_reason, llms, logs,
                      ua_check=ua_check)
