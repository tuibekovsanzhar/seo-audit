"""A scripted website plus fake citation records for the ANS panel.

The citation records stand in for Maya's prompt tracking or a paid API (T4). They are
written to a JSON file by the tests and the demo, exactly as an operator would pass it
with --citations.
"""

from __future__ import annotations

import json
import os

from .scenarios import Scenario, robots
from .server import Response, Site

FAST_ANS = {"request_delay_s": 0.0, "request_timeout_s": 2.0, "robots_sample_interval_s": 0.05,
            "probe_retry_cooldown_s": 0.0, "refetch_delay_s": 0.0, "prf_round_gap_s": 0.0, "render_enabled": False}

NAV = ("<nav>" + " ".join(f'<a href="{p}">{p}</a>' for p in
                          ("/", "/pricing", "/about", "/healthy", "/old-post", "/noindex-page", "/app",
                           "/guides/ai-visibility", "/internal/private")) + "</nav>")


def page(title: str, body: str, head: str = "") -> Response:
    return Response(body=f"<!doctype html><html lang='en'><head><title>{title}</title>{head}</head>"
                         f"<body>{NAV}<main><h1>{title}</h1>{body}</main></body></html>")


def ans_site() -> Site:
    return Site({
        "/robots.txt": robots("User-agent: *\nDisallow: /internal/\n\n"
                              "User-agent: OAI-SearchBot\nDisallow: /guides/\n"),
        "/": page("Acme", "<p>Acme builds analytics tools for product teams.</p>"),
        "/pricing": page("Pricing", "<p>The Pro plan costs $49/mo. The Starter plan costs $9/mo.</p>"),
        "/about": page("About", "<p>Acme was founded in 2012 in Berlin. We are a team of 40 people.</p>"),
        "/healthy": page("Guide", "<p>A healthy page that engines cite and that passes every site check.</p>"),
        # Cited, not linked from anywhere, and canonicalised elsewhere. ANS-1 follows the canonical and compares:
        # the same visible text as /healthy, so the citation is handed to a live page (consolidated).
        "/cited-canonical": page("Guide", "<p>A healthy page that engines cite and that passes every site check.</p>",
                                 head='<link rel="canonical" href="/healthy">'),
        # Canonicalised to a page with different content: IDX-4's S2 case.
        "/cited-canonical-other": page("Old pricing", "<p>Our plans used to start at twelve dollars a month.</p>",
                                       head='<link rel="canonical" href="/about">'),
        # Redirects into a 404: the citation now leads to an error (IDX-1 decision 15: S2).
        "/moved-broken": Response(301, "", {"Location": "/gone"}),
        "/old-post": Response(301, "", {"Location": "/new-post"}),
        "/new-post": page("New post", "<p>The post moved here.</p>"),
        "/noindex-page": page("Noindex page", "<p>Still served, but marked noindex.</p>",
                              head='<meta name="robots" content="noindex">'),
        # A client-rendered shell: RND-1 reports the content gap, and ANS-1 copies that severity.
        "/app": Response(
            body="<!doctype html><html lang='en'><head><title>App</title></head><body>" + NAV +
                 "<div id='root'></div><noscript>You need to enable JavaScript to run this app.</noscript>"
                 "<script src='/app.js'></script></body></html>"),
        "/app.js": Response(body="document.getElementById('root').innerHTML = '<main><h1>App</h1></main>';",
                            content_type="application/javascript"),
        "/guides/ai-visibility": page("AI visibility guide", "<p>A guide that OAI-SearchBot may not fetch.</p>"),
        "/internal/private": page("Internal", "<p>Robots.txt disallows this for everyone.</p>"),
    })


def citation_records(base: str) -> dict:
    """Citation data as the operator would supply it: two engines, one off-site URL, two invalid records."""
    return {
        "source": "maya prompt tracking",
        "fetched_at": "2026-09-15T09:00:00Z",
        "refresh_cadence": "daily",
        "sample": {"prompts": 120, "answers": 340},
        "records": [
            {"engine": "chatgpt", "model": "gpt-5", "cited_at": "2026-09-14T10:00:00Z", "url": base + "/pricing",
             "prompt": "how much does acme cost?",
             "answer_excerpt": "Acme has two plans. The Pro plan costs $39/mo and includes 10 seats.",
             "claims": [{"text": "The Pro plan costs $39/mo", "kind": "price", "value": "39", "subject": "Pro plan"}]},
            {"engine": "perplexity", "model": "sonar", "cited_at": "2026-09-13T08:00:00Z", "url": base + "/pricing",
             "prompt": "acme pricing",
             "answer_excerpt": "Acme's Pro plan is $49/mo.",
             "claims": [{"text": "Pro plan is $49/mo", "kind": "price", "value": "49"}]},
            # No claims supplied: Maya reads the price out of the answer itself (T0 fallback).
            {"engine": "perplexity", "model": "sonar", "cited_at": "2026-09-12T08:00:00Z", "url": base + "/pricing",
             "prompt": "acme pro price", "answer_excerpt": "Pro is $29 per month for small teams."},
            {"engine": "chatgpt", "model": "gpt-5", "cited_at": "2026-09-11T10:00:00Z", "url": base + "/about",
             "prompt": "when was acme founded?",
             "answer_excerpt": "Acme was founded in 2010 in Berlin.",
             "claims": [{"text": "Acme was founded in 2010", "kind": "fact", "value": "2010"},
                        # On the page: a match, not a conflict.
                        {"text": "Acme is based in Berlin", "kind": "fact", "value": "Berlin"},
                        # Not on the page at all: absent, which is a review item, never a conflict.
                        {"text": "Acme offers a free trial", "kind": "fact", "value": "free trial"},
                        # Compared upstream by a model: used as given, and labelled so.
                        {"text": "Acme has 45 employees", "kind": "fact", "value": "45",
                         "comparison": {"verdict": "contradicted", "page_quote": "We are a team of 40 people.",
                                        "method": "llm (upstream)"}}]},
            {"engine": "chatgpt", "model": "gpt-5", "cited_at": "2026-09-14T11:00:00Z", "url": base + "/removed",
             "prompt": "acme changelog", "answer_excerpt": "See the changelog."},
            {"engine": "perplexity", "model": "sonar", "cited_at": "2026-09-10T08:00:00Z", "url": base + "/old-post",
             "prompt": "acme post", "answer_excerpt": "An older post."},
            {"engine": "chatgpt", "model": "gpt-5", "cited_at": "2026-09-09T10:00:00Z", "url": base + "/noindex-page",
             "prompt": "acme internals", "answer_excerpt": "A page that is served but noindexed."},
            {"engine": "perplexity", "model": "sonar", "cited_at": "2026-09-08T08:00:00Z", "url": base + "/app",
             "prompt": "acme app", "answer_excerpt": "The app dashboard."},
            {"engine": "chatgpt", "model": "gpt-5", "cited_at": "2026-09-07T10:00:00Z",
             "url": base + "/guides/ai-visibility", "prompt": "ai visibility guide",
             "answer_excerpt": "Acme's guide to AI visibility."},
            {"engine": "chatgpt", "model": "gpt-5", "cited_at": "2026-09-06T10:00:00Z",
             "url": base + "/internal/private", "prompt": "acme internal", "answer_excerpt": "An internal page."},
            {"engine": "perplexity", "model": "sonar", "cited_at": "2026-09-05T08:00:00Z", "url": base + "/healthy",
             "prompt": "acme guide", "answer_excerpt": "Acme publishes a guide for product teams."},
            # Maya's real record shape (checked against the live API 2026-09-16): the provider is in "model",
            # there is no "engine", the URL has no scheme and carries the engine's tracking query, the answer text
            # fields are null, and only a promptId is given.
            {"domain": "{host}", "url": "{host}/healthy?utm_source=chatgpt.com", "model": "chatgpt", "kind": None,
             "sourceType": None, "title": None, "snippet": None, "contextBefore": None, "contextAfter": None,
             "promptId": "00000000-0000-4000-8000-000000000000", "citedAt": "2026-09-15T20:10:19.085Z"},
            {"engine": "gemini", "model": "g", "cited_at": "2026-09-14T09:00:00Z", "url": base + "/cited-canonical",
             "prompt": "acme guide", "answer_excerpt": "A guide."},
            {"engine": "gemini", "model": "g", "cited_at": "2026-09-13T09:00:00Z", "url": base + "/cited-canonical-other",
             "prompt": "acme old pricing", "answer_excerpt": "Old plans."},
            {"engine": "gemini", "model": "g", "cited_at": "2026-09-12T09:00:00Z", "url": base + "/moved-broken",
             "prompt": "acme moved", "answer_excerpt": "A moved page."},
            # Cited page on another site: recorded, never fetched.
            {"engine": "perplexity", "model": "sonar", "cited_at": "2026-09-04T08:00:00Z",
             "url": "https://news.example.com/acme-raises", "prompt": "acme news",
             "answer_excerpt": "Acme raised a round."},
            # Invalid: no url, and a url that is not http(s).
            {"engine": "chatgpt", "cited_at": "2026-09-03T10:00:00Z", "answer_excerpt": "No URL here."},
            {"engine": "chatgpt", "url": "ftp://example.com/file", "cited_at": "2026-09-02T10:00:00Z"},
        ],
    }


def write_citations(directory: str, base: str, records: dict | None = None) -> str:
    """`{host}` in a record is replaced with the site's host:port, so a scheme-less URL can be tested."""
    path = os.path.join(directory, "citations.json")
    payload = json.dumps(records if records is not None else citation_records(base), indent=2)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(payload.replace("{host}", base.split("//", 1)[1]))
    return path


def empty_records() -> dict:
    """Data supplied, zero citations: must read as 0, never as "no data"."""
    return {"source": "maya prompt tracking", "fetched_at": "2026-09-15T09:00:00Z", "refresh_cadence": "daily",
            "records": []}


ANS_SCENARIOS: dict[str, Scenario] = {s.name: s for s in [
    Scenario("ans_cited_pages", "Cited pages that 404, redirect, are noindexed, are client-rendered, are disallowed "
             "for a search bot or for everyone, plus healthy ones, with answers that quote a stale price and a wrong "
             "founding year.", ans_site, FAST_ANS),
]}


def domain_rows(base: str, *, truncated: bool = True, site_engines: dict | None = None) -> dict:
    """A cited-domain export shaped like Maya's `get_citations` payload.

    Mentions are deliberately small and hand-checkable so a test can assert an exact share.
    `site_engines` overrides which engines cite the site, so a test can create an engine that
    cites the topic and never this site.
    """
    host = base.split("//", 1)[1]
    engines = {"chatgpt": 40, "perplexity": 60} if site_engines is None else site_engines
    return {
        "project": {"name": "Fake Site", "domain": host},
        "period": {"sinceDays": 30},
        "page": {"limit": 5, "returned": 5, "total": 500 if truncated else 5},
        "totalMentions": 1000, "uniqueDomains": 500 if truncated else 5,
        "fetched_at": "2026-09-15T09:00:00Z",
        "domains": [
            {"domain": host, "mentions": sum(engines.values()), "byModel": dict(engines)},
            {"domain": "rival.example", "mentions": 150, "byModel": {"chatgpt": 90, "perplexity": 60}},
            {"domain": "images.openai.com", "mentions": 120, "byModel": {"chatgpt": 120}},
            {"domain": "en.wikipedia.org", "mentions": 80, "byModel": {"perplexity": 80}},
            {"domain": "instagram.com", "mentions": 30, "byModel": {"chatgpt": 30}},
        ],
    }


def write_domain_rows(directory: str, base: str, rows: dict | None = None) -> str:
    path = os.path.join(directory, "citation-domains.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(rows if rows is not None else domain_rows(base), indent=2))
    return path
