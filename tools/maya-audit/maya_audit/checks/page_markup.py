"""Page-level markup TSEO-1 reads besides titles and headings (review fixes H30, H32, H33).

What the raw HTML alone says about how a page loads and how it is measured: scripts in <head> that block the first
render, a missing or zoom-blocking viewport, sub-resources asked over plain http:// on an https page, and analytics
tags printed so that a visit may be counted twice. Each is read from `maya_audit.analysis` records; nothing here is
fetched. They sit in TSEO-1 rather than a new check id so the check catalogue stays as the owner set it; each finding
names TSEO-1 where it is made, as the catalogue tests read the titles from the source.
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlsplit

from ..config import BLOCKING_SCRIPTS_FINDING_MIN, SYNC_REQUIRED_SCRIPT_HOSTS
from ..findings import Finding, Rationale, Severity, scope_for
from ..models import Confidence
from ..urls import normalize_url, registrable_domain

EVIDENCE_LIMIT = 40
PAGE_SPEED = ["page speed for every reader"]
# Script types a browser runs as classic scripts (an empty type is one); type=module is deferred by default.
CLASSIC_SCRIPT_TYPES = frozenset({"", "text/javascript", "application/javascript", "application/ecmascript",
                                  "text/ecmascript"})


# A markup note on at least this share of the pages read (and on SITEWIDE_MIN of them) is one site-wide note (G11-G14):
# a template's habit, said once with its page count, not a list of pages.
SITEWIDE_SHARE = 0.5
SITEWIDE_MIN = 3


def _finding(check_id, title, severity, confidence, rationale, engines, urls, evidence, expected, fix, key_urls,
             notes=(), pages_read: int = 0) -> Finding:
    """The same argument order as `structure._finding` (the wording tests read the fields by position). With
    `pages_read`, a note on most of the pages is scoped site-wide."""
    sitewide = len(urls) >= SITEWIDE_MIN and len(urls) >= SITEWIDE_SHARE * pages_read > 0
    return Finding(check_id, title, severity, confidence, rationale, engines, scope_for(urls, sitewide), evidence, expected,
                   fix, notes=list(notes), importance_tier=0 if any(url in key_urls for url in urls) else 2)


def blocking_scripts(analysis: dict) -> list[str]:
    """External classic scripts in <head> with neither async nor defer: the browser stops building the page until
    each is downloaded and run."""
    return [s["src"] for s in analysis.get("external_scripts") or []
            if s.get("in_head") and not s.get("async") and not s.get("defer") and s.get("type", "") in CLASSIC_SCRIPT_TYPES]


def _host(src: str, page_url: str) -> str:
    return (urlsplit(normalize_url(src, page_url) or src).hostname or "").lower()


def sync_required(host: str) -> bool:
    """A script host whose vendor documents a synchronous load in <head> (`SYNC_REQUIRED_SCRIPT_HOSTS`, G11)."""
    return any(host == known or host.endswith("." + known) for known in SYNC_REQUIRED_SCRIPT_HOSTS)


def blocking_rows(pages: list) -> tuple[list[dict], dict]:
    """Per page, the render-blocking head scripts a developer could defer (sync-required vendors left out), and how
    many are the site's own; with a site-wide summary for the observation (G11)."""
    rows, hosts, left_out = [], Counter(), 0
    for p in pages:
        site = registrable_domain(urlsplit(p.url).hostname or "")
        kept, own = [], 0
        for src in blocking_scripts(p.analysis):
            host = _host(src, p.url)
            if sync_required(host):
                left_out += 1
                continue
            kept.append(src)
            hosts[host or "(relative)"] += 1
            own += registrable_domain(host) == site
        if kept:
            rows.append({"url": p.url, "scripts": len(kept), "own_scripts": own, "examples": kept[:5]})
    return rows, {"metric": "render-blocking scripts in <head> (classic, no defer or async)",
                  "pages": len(rows), "pages_read": len(pages), "scripts": sum(r["scripts"] for r in rows),
                  "top_hosts": [{"host": h, "scripts": n} for h, n in hosts.most_common(5)],
                  "sync_required_left_out": left_out,
                  "finding_when": f"a page blocks on at least {BLOCKING_SCRIPTS_FINDING_MIN} of the site's own scripts"}


def page_markup_findings(pages: list, key_urls: set[str], observations: list | None = None) -> list[Finding]:
    """TSEO-1's markup notes. Signals most healthy sites show (a theme's jQuery in <head>, a Tag Manager container
    beside a direct gtag) go to `observations`, not findings (review G, section 2)."""
    findings = []
    rows, summary = blocking_rows(pages)
    if rows and observations is not None:
        observations.append(summary)
    blocking = [row for row in rows if row["own_scripts"] >= BLOCKING_SCRIPTS_FINDING_MIN]
    if blocking:
        urls = [row["url"] for row in blocking]
        findings.append(_finding(
            "TSEO-1", f"{len(urls)} page(s) load {sum(row['scripts'] for row in blocking)} script(s) in <head> without defer or async",
            Severity.INFO, Confidence.VERIFIED, Rationale.DOCUMENTED.value, PAGE_SPEED, urls, {"pages": blocking[:EVIDENCE_LIMIT]},
            "scripts in <head> load with defer or async, or sit at the end of <body>",
            "Add defer to scripts that do not need to run before the page shows (most theme and plugin scripts), or "
            "async to independent ones such as analytics; test that the page still works.", key_urls,
            ["A script without defer or async in <head> holds up the first render until it is downloaded and run; "
             "which of them the page truly needs early is for the developer to decide."], len(pages)))
    no_viewport, no_zoom, insecure = [], [], []
    for p in pages:
        viewports = [m["content"] for m in p.analysis.get("meta") or [] if m["name"] == "viewport"]
        if not viewports:
            # One printed after the body started is not the head's, but browsers still apply it: not "missing".
            if "viewport" not in ((p.analysis.get("outside_head") or {}).get("meta") or []):
                no_viewport.append(p.url)
        elif blocks_zoom(viewports[0]):
            no_zoom.append({"url": p.url, "viewport": viewports[0][:200]})
        if p.url.lower().startswith("https://") and p.analysis.get("insecure_refs"):
            insecure.append({"url": p.url, "resources": p.analysis["insecure_refs"][:10]})
    if no_viewport:
        findings.append(_finding(
            "TSEO-1", f"{len(no_viewport)} page(s) have no viewport meta tag", Severity.S3, Confidence.VERIFIED,
            Rationale.DOCUMENTED.value, ["Google (mobile-first indexing)", "every mobile reader"], no_viewport,
            {"pages": no_viewport[:EVIDENCE_LIMIT]}, "a viewport meta tag in every page's <head>",
            'Add <meta name="viewport" content="width=device-width, initial-scale=1"> to the <head> of the page template.',
            key_urls, ["Without it a phone lays the page out at desktop width and shrinks it; Google indexes the mobile "
                       "version of a page."]))
    if no_zoom:
        findings.append(_finding(
            "TSEO-1", f"{len(no_zoom)} page(s) stop readers from zooming (user-scalable=no or maximum-scale=1)",
            Severity.INFO, Confidence.VERIFIED, Rationale.DOCUMENTED.value, ["every mobile reader"],
            [row["url"] for row in no_zoom], {"pages": no_zoom[:EVIDENCE_LIMIT]}, "a viewport that lets readers zoom",
            "Remove user-scalable=no and maximum-scale=1 from the viewport meta tag.", key_urls,
            ["WCAG 1.4.4 asks that text can be resized to 200%; some browsers ignore the setting, others obey it."]))
    if insecure:
        urls = [row["url"] for row in insecure]
        findings.append(_finding(
            "TSEO-1", f"{len(urls)} https page(s) load resources over plain http:// (mixed content)", Severity.S3,
            Confidence.VERIFIED, Rationale.SELF_EVIDENT.value, ["every reader of the page"], urls,
            {"pages": insecure[:EVIDENCE_LIMIT]}, "every image, script, style and frame of an https page asked over https",
            "Change each http:// address listed to https:// (or a relative address) in the page or template.", key_urls,
            ["Browsers block http:// scripts, styles and frames on an https page and may upgrade or flag images; "
             "the page then breaks or shows as not fully secure."]))
    findings += head_closed_early_findings(pages, key_urls)
    doubled = [{"url": p.url, **why} for p in pages if (why := double_counting(p.analysis))]
    both = [p.url for p in pages if tag_manager_beside_gtag(p.analysis)]
    if both and observations is not None:
        observations.append({"metric": "pages with a Tag Manager container beside a direct gtag.js (different ids)",
                             "pages": len(both), "examples": both[:5],
                             "note": "common and usually intended (a shop's Google channel, an Ads tag); a double "
                                     "count only if the container sends the same property, which the markup cannot show"})
    if doubled:
        urls = [row["url"] for row in doubled]
        findings.append(_finding(
            "TSEO-1", f"{len(urls)} page(s) load the same analytics tag more than once (possible double counting)",
            Severity.INFO, Confidence.ESTIMATED, Rationale.HYPOTHESIS.value, ["the site's own analytics"], urls,
            {"pages": doubled[:EVIDENCE_LIMIT]}, "each tag-manager container and analytics property loaded once per page",
            "Confirm with Tag Assistant (or the browser's network panel) which tags fire, then remove the duplicate "
            "snippet, or the direct gtag when the same property is also set up inside Tag Manager.", key_urls,
            ["Read from the markup: whether a visit is really counted twice depends on how the container is set up, "
             "which only Tag Assistant or the analytics property can show."], len(pages)))
    return findings


# Google: "Once Google detects one of these invalid elements, it assumes the end of the head element and stops reading
# any further elements in the head element." (Search Central, "Use valid HTML for page metadata").
HEAD_DOCUMENTED = ("Documented (Google Search Central: an element that is invalid in <head> ends the head there; Google "
                   "stops reading metadata after it)")
ROBOTS_META = {"robots", "googlebot", "bingbot"}
# DECISIONS 338: a robots tag lost after the break matters only when it says something (noindex, nofollow, a snippet
# limit ...). "index, follow" or "all" is what a crawler does anyway; an unrecorded value (a report saved before) is
# not counted as lost and is said as unknown.
RESTRICTIVE_ROBOTS = re.compile(r"\b(noindex|nofollow|none|noarchive|nocache|nosnippet|noimageindex|notranslate|"
                                r"max-snippet|max-image-preview|max-video-preview|unavailable_after|indexifembedded)\b", re.I)


def robots_lost(row: dict) -> bool:
    """Whether the robots tags after the break restrict anything (their recorded values)."""
    return any(RESTRICTIVE_ROBOTS.search(v or "") for v in row.get("robots_content") or [])


def place_head_row(row: dict, lost: list, later: list) -> None:
    """High (lost) when a canonical, the title, hreflang (none of them also in the head before the break) or a
    restricting robots tag is after the break; else Medium (later) when any meta or Open Graph tag is (DECISIONS 338)."""
    kept = set(row.get("kept_in_head") or [])
    # A second copy after the break, with the first in the head, is a duplicate: the head's copy is the one read.
    if ((row["canonical_after"] and "canonical" not in kept) or (row["hreflang_after"] and "hreflang" not in kept)
            or (row["title_after"] and "title" not in kept) or (row["robots_after"] and robots_lost(row))):
        lost.append(row)
    elif row["meta_after"] or row["properties_after"] or row["robots_after"]:
        later.append(row)


def kept_in_head(analysis: dict) -> list[str]:
    """The tags that stay in the head, before the break: what the head still carries (DECISIONS 338)."""
    out = []
    if analysis.get("canonicals"):
        out.append("canonical")
    if analysis.get("hreflang"):
        out.append("hreflang")
    if (analysis.get("title") or "") and not (analysis.get("outside_head") or {}).get("title"):
        out.append("title")
    if any((m.get("name") or "") in ROBOTS_META for m in analysis.get("meta") or [] if isinstance(m, dict)):
        out.append("robots")
    return out


HEAD_KEPT_NOTE = ("Medium, not High: no canonical, hreflang, title or restricting robots tag (noindex, nofollow ...) comes "
                  "after the break; evidence.kept_in_head lists what the head still holds before it. Without the "
                  "description Google writes the snippet from the page text.")


def head_closed_early_findings(pages: list, key_urls: set[str]) -> list[Finding]:
    """A <div>, <img> or other body element printed inside <head> (often by a widget) ends the head there (DECISIONS
    260). A canonical, a title, hreflang or a robots tag that restricts something after it is lost to Google: High.
    Only meta (a plain robots tag included) or Open Graph tags after it: Medium (DECISIONS 338). The element that ended
    the head is named so the developer can find the widget, and each row says what stays in the head before it."""
    lost, later = [], []
    for p in pages:
        out = p.analysis.get("outside_head") or {}
        culprit = out.get("closed_early_by")
        if not culprit:
            continue
        robots = sorted(ROBOTS_META & set(out.get("meta") or []))
        row = {"url": p.url, "closed_by": culprit, "canonical_after": out.get("canonical", 0),
               "robots_after": robots, "robots_content": out.get("robots_content"),  # None: not recorded (saved before)
               "hreflang_after": out.get("hreflang", 0),
               "meta_after": sorted(set(out.get("meta") or []) - ROBOTS_META)[:10],
               "properties_after": sorted(set(out.get("properties") or []))[:10], "title_after": out.get("title", 0),
               "kept_in_head": kept_in_head(p.analysis)}
        place_head_row(row, lost, later)
    findings = []
    fix = ("Move the element named in the evidence out of <head> (into <body>), or load the widget that prints it after "
           "the head's metadata; every <link>, <meta> and <title> must come before the first element that cannot stand "
           "in a head.")
    if lost:
        urls = [row["url"] for row in lost]
        findings.append(_finding(
            "TSEO-1", f"{len(urls)} page(s) end <head> early: canonical, robots or hreflang tags after it are read as body",
            Severity.S2, Confidence.VERIFIED, HEAD_DOCUMENTED, ["Google", "every crawler that follows the HTML standard"],
            urls, {"pages": lost[:EVIDENCE_LIMIT]}, "the canonical, robots and hreflang tags before any body element",
            fix, key_urls, ["Verified from the HTML: the element is inside <head> and the tags come after it. What Google "
                            "then uses can be confirmed in Search Console's URL Inspection (user-declared canonical)."]))
    if later:
        urls = [row["url"] for row in later]
        findings.append(_finding(
            "TSEO-1", f"{len(urls)} page(s) end <head> early: meta or Open Graph tags after it are read as body",
            Severity.S3, Confidence.VERIFIED, HEAD_DOCUMENTED, ["Google", "social and AI previews"],
            urls, {"pages": later[:EVIDENCE_LIMIT]}, "every meta and Open Graph tag before any body element",
            fix, key_urls, ["Verified from the HTML. Which tags a given consumer still reads from the body varies.",
                            HEAD_KEPT_NOTE]))
    return findings


def double_counting(analysis: dict) -> dict | None:
    """H33: a Tag Manager container whose loader or <noscript> frame is printed more than once, or one gtag.js id
    loaded more than once. A container beside a direct gtag.js for another id is not one (G10): it is how a shop's
    Google channel or an Ads tag sits beside the site's own container, and whether the container sends the same
    property the markup cannot show (an observation, `tag_manager_beside_gtag`). A preload <link> is not a loader."""
    ids = analysis.get("analytics_ids") or {}
    scripts, frames, gtags = ids.get("gtm_script") or {}, ids.get("gtm_noscript") or {}, ids.get("gtag") or {}
    repeated = sorted({gtm for gtm, n in [*scripts.items(), *frames.items()] if n > 1})
    containers = sorted({*scripts, *frames})
    direct = sorted(tag for tag in gtags if tag.startswith(("G-", "GT-")))
    reasons = ([f"{gtm} printed more than once (script {scripts.get(gtm, 0)}, noscript {frames.get(gtm, 0)})"
                for gtm in repeated]
               + [f"gtag.js for {tag} loaded {n} times" for tag, n in sorted(gtags.items()) if n > 1])
    if not reasons:
        return None
    return {"containers": containers, "measurement_ids": direct, "why": reasons}


def tag_manager_beside_gtag(analysis: dict) -> bool:
    """A Tag Manager container and a direct gtag.js for a Google Analytics property on one page (G10: observed)."""
    ids = analysis.get("analytics_ids") or {}
    containers = {*(ids.get("gtm_script") or {}), *(ids.get("gtm_noscript") or {})}
    return bool(containers) and any(tag.startswith(("G-", "GT-")) for tag in ids.get("gtag") or {})


def blocks_zoom(content: str) -> bool:
    """user-scalable=no (or 0), or a maximum-scale of 1 or less, in a viewport meta tag's content."""
    values = {}
    for part in content.replace(";", ",").split(","):
        key, _, value = part.partition("=")
        values[key.strip().lower()] = value.strip().lower()
    if values.get("user-scalable") in ("no", "0"):
        return True
    try:
        return float(values["maximum-scale"]) <= 1
    except (KeyError, ValueError):
        return False
