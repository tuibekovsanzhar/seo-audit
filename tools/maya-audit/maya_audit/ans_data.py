"""Citation data (T4) for the ANS panel, and the site-side fetches it needs.

Maya's own prompt tracking or a paid API (for example DataForSEO LLM Mentions)
produces the citation records; this build reads them from a JSON file the operator
passes with --citations. Nothing here calls a metered API, so the T4 cost is paid
upstream. The file is operator input and is validated, never trusted: a bad record
is reported, not crashed on.

Record shape, checked against Maya's live citation API on 2026-09-16
(`get_citation_examples`, project Withmaya):

    {"domain": "withmaya.ai",
     "url": "withmaya.ai/blog/best-ai-visibility-tools-2026?utm_source=chatgpt.com",
     "model": "chatgpt", "kind": null, "sourceType": null, "title": null,
     "snippet": null, "contextBefore": null, "contextAfter": null,
     "promptId": "a1cffe0b-...", "citedAt": "2026-09-13T17:05:17.365Z"}

Three things about the real data that this loader has to absorb:
  * **`url` has no scheme** and carries the engine's own tracking query
    (`?utm_source=chatgpt.com`). Missing schemes are read as https, and tracking
    parameters are stripped for matching while the original string is kept.
  * **There is no `engine` field**: the provider is in `model` ("chatgpt").
  * **There is no answer text and no claims**: `snippet`, `contextBefore`,
    `contextAfter` and `title` were null in every record checked, and Maya's
    prompt API returns no raw answer either. ANS-2 therefore has nothing to
    compare on this export and reports Not assessed (see the README).

Both spellings are accepted, so a file can also use the plainer form:

    {"source": "maya prompt tracking", "fetched_at": "2026-09-14T09:00:00Z",
     "refresh_cadence": "daily", "sample": {"prompts": 120, "answers": 340},
     "records": [
       {"engine": "chatgpt", "model": "gpt-5", "cited_at": "2026-09-10T12:00:00Z",
        "url": "https://example.com/pricing", "prompt": "...", "answer_excerpt": "...",
        "claims": [{"text": "Pro costs $39/mo", "kind": "price", "value": "39", "subject": "Pro"}]}]}

A record needs a usable engine (`engine`, else `model`) and `url`. `claims` are
extracted from the answer by an LLM upstream (T4); when a record has none, ANS-2
falls back to reading prices out of the answer text with the same T0 tokenizer the
STR checks use.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .config import CrawlConfig
from .fetcher import Fetcher
from .html_links import decode_body, is_html
from .analysis import analyze_html
from .classify import classify_fetch
from .models import CrawlResult
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .urls import normalize_url, same_origin

# Query parameters the engines add to a cited URL; removed before matching it against the crawl.
TRACKING_PARAMS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
                   "ref", "ref_src", "referrer", "fbclid", "gclid", "msclkid", "srsltid")


def strip_tracking(url: str) -> str:
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def _bare(netloc: str) -> str:
    return netloc.casefold().removeprefix("www.")


def read_url(raw: str, origin: str = "") -> tuple[str | None, bool, bool]:
    """(normalized url, scheme was assumed, host was aligned to the audited site).

    Two things the real records need. **Scheme:** Maya's records carry "example.com/page" with no
    scheme, so a record on the audited site's host takes that site's scheme and anything else is read
    as https. **www:** the records name the bare domain ("enpara.com") while the same site may be
    crawled as "www.enpara.com". Without aligning them, every cited URL looks like another site's and
    ANS-1 silently reports zero cited pages. Fragments (including Chrome's "#:~:text=" quote links)
    are dropped by normalize_url, since they never reach the server.
    """
    text = raw.strip()
    origin_parts = urlsplit(origin)
    assumed = not urlsplit(text).scheme
    if assumed:
        host = urlsplit("//" + text.lstrip("/")).netloc
        scheme = origin_parts.scheme if host and _bare(host) == _bare(origin_parts.netloc) else "https"
        text = f"{scheme}://" + text.lstrip("/")
    url = normalize_url(text)
    if url is None:
        return None, assumed, False
    parts = urlsplit(url)
    aligned = bool(origin_parts.netloc) and parts.netloc.casefold() != origin_parts.netloc.casefold() \
        and _bare(parts.netloc) == _bare(origin_parts.netloc)
    if aligned:  # same site, spelled with or without www
        url = urlunsplit((origin_parts.scheme, origin_parts.netloc, parts.path, parts.query, ""))
    return strip_tracking(url), assumed, aligned


def answer_text(record: dict) -> str | None:
    """The answer text, under whichever name the source uses. Maya's export has none of these filled in."""
    for key in ("answer_excerpt", "snippet", "answer", "text"):
        if isinstance(record.get(key), str) and record[key].strip():
            around = " ".join(str(record.get(k) or "") for k in ("contextBefore", "contextAfter"))
            return (record[key] + (" " + around if around.strip() else "")).strip()
    return None


@dataclass
class CitationData:
    path: str | None = None
    loaded: bool = False
    error: str | None = None
    source: str | None = None
    fetched_at: str | None = None
    refresh_cadence: str | None = None
    sample: dict[str, Any] | None = None
    records: list[dict[str, Any]] = field(default_factory=list)
    invalid_records: list[dict[str, Any]] = field(default_factory=list)
    off_site: list[dict[str, Any]] = field(default_factory=list)
    # url -> site-side observation for cited URLs the crawl did not fetch
    extra_fetches: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def engines(self) -> list[str]:
        return sorted({r["engine"] for r in self.records})

    def freshness(self) -> str:
        return (f"citation data from {self.source or 'an unnamed source'}, fetched {self.fetched_at or 'at an unknown time'}"
                f" (upstream refresh: {self.refresh_cadence or 'unknown'})")


def load_citations(path: str | None, origin: str) -> CitationData:
    data = CitationData(path=path)
    if not path:
        return data
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError) as exc:
        data.error = f"{type(exc).__name__}: {exc}"
        return data
    # Maya's `get_citation_examples` returns its rows under "examples"; a file assembled by hand
    # uses "records". Both are accepted so the tool's own export can be saved and passed straight in
    # — rewrapping it by hand was a step every operator had to repeat, and a step that can be
    # skipped is a step that cannot be got wrong.
    rows = next((raw[k] for k in ("records", "examples")
                 if isinstance(raw, dict) and isinstance(raw.get(k), list)), None)
    if rows is None:
        data.error = "expected a JSON object with a 'records' or 'examples' list"
        return data
    data.loaded = True
    for key in ("source", "fetched_at", "refresh_cadence"):
        value = raw.get(key)
        setattr(data, key, value if isinstance(value, str) else None)
    if data.source is None and isinstance(raw.get("project"), dict):
        name = raw["project"].get("name") or raw["project"].get("id")
        data.source = f"Maya get_citation_examples ({name})" if name else "Maya get_citation_examples"
    period = raw.get("period") if isinstance(raw.get("period"), dict) else {}
    if data.fetched_at is None and isinstance(period.get("since"), str):
        # "since" is the start of the window, not the fetch time. Labelled as the window so the
        # freshness line does not imply a precision the payload does not carry.
        data.fetched_at = f"covering {period['since']} onward"
    data.sample = raw.get("sample") if isinstance(raw.get("sample"), dict) else None
    if data.sample is None and isinstance(raw.get("page"), dict):
        data.sample = {k: v for k, v in raw["page"].items() if k in ("returned", "total", "hasMore")}
    for index, record in enumerate(rows):
        if not isinstance(record, dict):
            data.invalid_records.append({"index": index, "reason": "not a JSON object"})
            continue
        # Maya's records name the provider in "model" and have no "engine" field.
        engine = next((record[k].strip() for k in ("engine", "model", "provider")
                       if isinstance(record.get(k), str) and record[k].strip()), None)
        missing = [k for k in ("engine (or model)", "url")
                   if (engine is None if k.startswith("engine") else
                       not isinstance(record.get("url"), str) or not record["url"].strip())]
        if missing:
            data.invalid_records.append({"index": index, "reason": f"missing or non-string: {', '.join(missing)}",
                                         "record": {k: record.get(k) for k in list(record)[:6]}})
            continue
        # A URL with user:pass@ names a host that is not the one a reader sees first; normalize_url would drop the
        # userinfo silently and credit this site with it (the check OpenSEO's safeUrl.ts makes).
        if urlsplit(record["url"].strip() if "://" in record["url"] else "//" + record["url"].strip()).username:
            data.invalid_records.append({"index": index, "reason": "URL carries user:pass@ userinfo; not attributed "
                                                                   "to any site"})
            continue
        url, assumed_scheme, host_aligned = read_url(record["url"], origin)
        if url is None:
            data.invalid_records.append({"index": index, "reason": f"not a usable URL: {record['url']!r}"})
            continue
        claims = [c for c in record.get("claims") or [] if isinstance(c, dict) and isinstance(c.get("text"), str)]
        dropped = len(record.get("claims") or []) - len(claims)
        if dropped:
            data.invalid_records.append({"index": index, "reason": f"{dropped} claim(s) dropped: not an object with text"})
        entry = {"engine": engine, "model": record.get("model"),
                 "cited_at": record.get("cited_at") or record.get("citedAt"), "url": url,
                 "url_as_supplied": record["url"].strip(), "scheme_assumed": assumed_scheme,
                 "host_aligned_to_site": host_aligned,
                 "prompt": record.get("prompt") or (f"promptId {record['promptId']}" if record.get("promptId") else None),
                 "answer_excerpt": answer_text(record), "claims": claims, "index": index,
                 "kind": record.get("kind"), "source_type": record.get("sourceType"), "title": record.get("title")}
        (data.records if same_origin(url, origin) else data.off_site).append(entry)
    return data


def _next_hop(observation: dict, url: str) -> str | None:
    """Where a cited URL hands its citation on to: its redirect target, else its declared canonical."""
    from .index_data import link_header_canonicals  # local import: index_data imports nothing from here

    status = observation.get("status")
    if status and 300 <= status < 400:
        return observation.get("location")
    analysis = observation.get("analysis")
    if analysis:
        html = [u for u in (normalize_url(h, url) for h in analysis.get("canonicals", [])) if u]
        chosen = (html or link_header_canonicals((observation.get("headers") or {}).get("link"), url) or [None])[0]
        return chosen if chosen and chosen != url else None
    return None


def collect_ans_data(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig) -> CitationData:
    """Load the citation file, fetch cited same-origin URLs the crawl did not reach, then follow each cited
    URL's redirect or canonical to where it lands (ANS-1 v2), within the same fetch cap."""
    data = load_citations(cfg.citations_file, result.origin)
    if not data.loaded:
        return data
    crawled = {strip_tracking(p.url) for p in result.pages}
    pages = {p.url: p for p in result.pages}
    policy = result.robots_policy_by_origin.get(result.origin)
    queue = list(dict.fromkeys(r["url"] for r in data.records))
    hops: dict[str, int] = {url: 0 for url in queue}
    while queue:
        url = queue.pop(0)
        if url not in crawled and url not in data.extra_fetches:
            _fetch_cited(fetcher, data, cfg, policy, url, hops[url])
        # Follow the citation to where it lands (at most 5 hops), so ANS-1 can tell a URL that hands its
        # citation to a live page from one that hands it to an error.
        page = pages.get(url)
        seen = ({"status": page.status, "location": page.redirect_location, "analysis": page.analysis,
                 "headers": page.headers} if page is not None else data.extra_fetches.get(url) or {})
        target = _next_hop(seen, url) if seen.get("fetched", True) else None
        if target and same_origin(target, result.origin) and target not in hops and hops[url] < 5:
            hops[target] = hops[url] + 1
            queue.append(target)
    return data


def _fetch_cited(fetcher: Fetcher, data: CitationData, cfg: CrawlConfig, policy, url: str, hop: int) -> None:
    fetched_for = "cited URL" if hop == 0 else "where a cited URL redirects or canonicalizes to"
    if sum(1 for v in data.extra_fetches.values() if v.get("fetched")) >= cfg.ans_max_fetches:
        data.extra_fetches[url] = {"url": url, "fetched": False, "fetched_for": fetched_for,
                                   "reason": f"cited-URL fetch cap of {cfg.ans_max_fetches} reached"}
        return
    if policy is not None and not policy.decide(cfg.product_token, url).allowed:
        data.extra_fetches[url] = {"url": url, "fetched": False, "fetched_for": fetched_for,
                                   "reason": "robots.txt disallows Maya's user agent for this URL"}
        return
    response = fetcher.get(url, "ans_cited_url", cfg.max_body_bytes)
    classification = classify_fetch(response.status, response.headers, response.body, response.error)
    content_type = response.headers.get("content-type")
    analysis = None
    if response.status and 200 <= response.status < 300 and is_html(content_type) and response.body:
        analysis = analyze_html(decode_body(response.body, content_type))
    data.extra_fetches[url] = {
        "url": url, "fetched": True, "fetched_for": fetched_for, "requested_at": response.started_at,
        "status": response.status,
        "error": response.error, "fetch_class": classification.fetch_class.value, "content_type": content_type,
        "location": normalize_url(response.headers["location"], url) if response.headers.get("location") else None,
        "headers": dict(response.headers), "analysis": analysis}
