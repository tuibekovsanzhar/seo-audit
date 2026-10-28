"""Structured evidence for the most frequent findings (DECISIONS 271).

A finding's evidence is shaped by the check that wrote it. For the rules below, this pass adds `evidence["facts"]`: a
short list of language-neutral rows a report can quote without reading the rest of the evidence:
    {"url": address, "element": what (a property, a tag, a file, a marker), "observed": value seen, "expected": the
     limit the value is judged against (a threshold), when there is one}
Each key is optional; values are taken from the evidence as the check recorded it, never re-measured. The pass is
idempotent and runs after rule ids are assigned (`maya_audit.rules`).

The same pass fills the finding contract the release gate reads (DECISIONS 278, schema 1.20), from the same evidence:
`measurement.claims` (what the finding says about which element on which page, `CLAIMS`) and `remediation` (the
catalogue task in rule_actions.json that fixes it, and the page kinds content advice may be given for). A rule with no
claim extractor gets no claims: unknown, not "none".
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Callable
from urllib.parse import urlsplit

MAX_FACTS = 5


def _kb(n) -> str | None:
    return f"{int(n) // 1000} KB" if isinstance(n, (int, float)) else None


def _file(url: str | None) -> str | None:
    return (urlsplit(url).path.rsplit("/", 1)[-1] or url) if url else None


def _row(**values) -> dict:
    return {k: v for k, v in values.items() if v not in (None, "", [])}


def _org(ev):
    # element: the property and line:column where the parser stopped; observed: the character's code point only.
    def code(c):
        return c[c.find("(") + 1:c.find(")")] if c and "(" in c else c
    return [_row(url=None, element=f"{b.get('in_property') or 'JSON-LD'} {b.get('line')}:{b.get('column')}",
                 observed=code(b.get("character"))) for b in ev.get("blocks") or [] if b.get("line")]


def _hidden_h1(ev):
    return [_row(url=p.get("url"), element="<h1>", observed=(p.get("h1") or [None])[0]) for p in ev.get("pages") or []]


def _ttfb(ev):
    return [_row(url=p.get("url"), observed=f"{round(p['median_ttfb_ms'])} ms" if p.get("median_ttfb_ms") else None,
                 expected=f"{ev.get('threshold_ms')} ms" if ev.get("threshold_ms") else None) for p in ev.get("pages") or []]


def _bytes(ev):
    return [_row(url=p.get("url"), observed=_kb(p.get("bytes")), expected=_kb(ev.get("threshold_bytes")))
            for p in ev.get("pages") or []]


def _images(ev):
    return [_row(url=(i.get("shown_on") or [None])[0], element=_file(i.get("image")), observed=_kb(i.get("bytes")))
            for i in ev.get("images") or []]


def _videos(ev):
    return [_row(url=(v.get("shown_on") or [None])[0], element=_file(v.get("video")), observed=_kb(v.get("bytes")),
                 expected=_kb(ev.get("threshold_bytes"))) for v in ev.get("videos") or []]


def _pages(ev):
    return [_row(url=p.get("url") if isinstance(p, dict) else p) for p in ev.get("pages") or []]


def _markers(ev):
    return [_row(url=f.get("url"), element=f.get("marker")) for f in ev.get("found") or []]


def _pairs(ev):
    return [_row(url=p.get("kept"), element=p.get("other")) for p in ev.get("pairs") or []]


def _og_site_name(ev):
    return [_row(url=p.get("url"), element="og:site_name", observed=p.get("og_site_name")) for p in ev.get("pages") or []]


def _shared_titles(ev):
    return [_row(url=(g.get("urls") or [None])[0], element="<title>", observed=g.get("title")) for g in ev.get("groups") or []]


def _referenced(ev):
    # DECISIONS 278: the page to edit first (url), the address its link names (element), the error it ends in.
    status = {p.get("url"): p.get("status") for p in ev.get("pages") or []}
    if ev.get("link_sources"):
        return [_row(url=r.get("source"), element=r.get("links_to"),
                     observed=str(status.get(r.get("target"))) if status.get(r.get("target")) else None)
                for r in ev["link_sources"]]
    return [_row(url=p.get("url"), observed=str(p.get("status")) if p.get("status") else None,
                 element=((p.get("referenced_by") or [{}])[0]).get("source")) for p in ev.get("pages") or []]


def _empty(ev):
    return [_row(url=p.get("url"), observed=f"{p.get('status')} · {p.get('body_bytes')} B")
            for p in ev.get("pages") or [] if p.get("body_bytes") is not None]


def _outline(ev):
    return [_row(url=p.get("url"), element="<h2>/<h3>", observed=str(len(p.get("visible_h2_h3") or [])))
            for p in ev.get("pages") or []]


def _head_closed(ev):
    def name(c):
        return f"<{c.get('tag')}{'#' + c['id'] if c.get('id') else ''}>"
    return [_row(url=p.get("url"), element=name(p.get("closed_by") or {})) for p in ev.get("pages") or []]


def _invalid(ev):
    return [_row(url=i.get("url"), element=pr.get("property"), observed=pr.get("value"))
            for i in ev.get("items") or [] for pr in i.get("problems") or []]


def _canonical_redirect(ev):
    return [_row(url=p.get("url"), element=p.get("canonical"), observed=p.get("redirects_to")) for p in ev.get("pages") or []]


EXTRACTORS: dict[str, Callable[[dict], list[dict]]] = {
    "str3.organization_broken": _org, "str2.home_hidden_h1": _hidden_h1, "prf1.home_ttfb": _ttfb,
    "rnd6.home_large": _bytes, "rnd6.large": _bytes, "str7.heavy": _images, "str7.video": _videos,
    "idx5.drafts": _pages, "str1.no_title": _pages, "str13.markers": _markers, "idx8.two_addresses": _pairs,
    "str5.og_site_name": _og_site_name, "str1.shared": _shared_titles, "idx1.4xx.referenced": _referenced,
    "idx1.4xx.referenced.linked": _referenced, "judgment.empty.repeated": _empty, "judgment.empty.single": _empty,
    "str2.home_outline": _outline, "tseo1.head_closed_lost": _head_closed, "tseo1.head_closed_later": _head_closed,
    "str3.invalid_values": _invalid, "idx4.redirect_loop": _canonical_redirect, "idx4.redirecting": _canonical_redirect,
}


def _claim(element, state, urls):
    urls = [u for u in urls if isinstance(u, str)]
    return {"element": element, "state": state, "urls": urls} if urls else None


def _h1_states(ev, urls, title=""):
    # One claim per state the evidence recorded; a state the parser could not tell is not claimed.
    rows = [r for r in ev.get("heading_assessments") or [] if isinstance(r, dict)]
    by_state: dict[str, list[str]] = {}
    for r in rows:
        if r.get("state") in ("absent", "empty"):
            by_state.setdefault(r["state"], []).append(r.get("url"))
    return [_claim("<h1>", state, us) for state, us in by_state.items()]


def _absent_tag(ev, urls, title=""):
    # "N page(s) have no og:title" / "... no meta description": the element is in the title the check wrote.
    m = re.search(r"have no (og:[\w:]+|meta description)$", title or "")
    return [_claim("description" if m.group(1) == "meta description" else m.group(1), "absent", urls)] if m else []


def _after_head(ev, urls, title=""):
    by_element: dict[str, list[str]] = {}
    for row in ev.get("pages") or []:
        names = list(row.get("properties_after") or []) + list(row.get("meta_after") or []) + list(row.get("robots_after") or [])
        names += ["canonical"] if row.get("canonical_after") else []
        for name in names:
            by_element.setdefault(name, []).append(row.get("url"))
    return [_claim(element, "after_head", us) for element, us in by_element.items()]


def _stray_robots(ev, urls, title=""):
    return [_claim("robots", "outside_head", list((ev.get("robots_tags_outside_head") or {}).keys()) or urls)]


CLAIMS: dict[str, Callable[[dict, list[str], str], list[dict | None]]] = {
    "str2.no_h1": _h1_states, "str2.empty_h1": _h1_states, "judgment.heading.pages": _h1_states,
    "str10.no_tag": _absent_tag, "str10.no_description": _absent_tag,
    "tseo1.head_closed_lost": _after_head, "tseo1.head_closed_later": _after_head,
    "acc3.robots_outside_head": _stray_robots,
}


def _get(value: Any, name: str):
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _set(value: Any, name: str, data) -> None:
    if isinstance(value, dict):
        value[name] = data
    else:
        setattr(value, name, data)


@lru_cache(maxsize=1)
def _catalogue() -> dict:
    import json
    from pathlib import Path
    try:
        return json.loads(Path(__file__).with_name("rule_actions.json").read_text(encoding="utf-8")).get("actions") or {}
    except (OSError, ValueError):
        return {}


def contract(finding) -> None:
    """`measurement.claims` and `remediation` of one finding (DECISIONS 278), from its evidence and the catalogue."""
    rule = _get(finding, "rule_id") or ""
    evidence = _get(finding, "evidence")
    scope = _get(finding, "scope") or {}
    urls = list(scope.get("_all_urls") or scope.get("urls") or []) if isinstance(scope, dict) else []
    extract = CLAIMS.get(rule)
    if extract is not None and isinstance(evidence, dict):
        try:
            claims = [c for c in extract(evidence, urls, _get(finding, "title") or "") if c]
        except (TypeError, ValueError, AttributeError, KeyError):
            claims = []
        if claims:
            measurement = dict(_get(finding, "measurement") or {})
            measurement["claims"] = claims
            _set(finding, "measurement", measurement)
    entry = _catalogue().get(rule)
    if entry is not None:
        remedy = {"task_id": rule, "content": bool(entry.get("content_page_types")),
                  "page_types": entry.get("content_page_types")}
        _set(finding, "remediation", {**(_get(finding, "remediation") or {}), **remedy})


def attach(checks) -> None:
    """Add `evidence["facts"]` to the findings whose rule has an extractor (native or saved checks), and fill the finding
    contract (`contract`)."""
    for check in checks:
        for finding in _get(check, "findings") or []:
            contract(finding)
            extract = EXTRACTORS.get(_get(finding, "rule_id") or "")
            evidence = _get(finding, "evidence")
            if extract is None or not isinstance(evidence, dict):
                continue
            try:
                rows = [r for r in extract(evidence) if r][:MAX_FACTS]
            except (TypeError, ValueError, AttributeError, KeyError):
                rows = []  # an older or partial evidence shape: no facts rather than a wrong one
            if rows:
                evidence["facts"] = rows
