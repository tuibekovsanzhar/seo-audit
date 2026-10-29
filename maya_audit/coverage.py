"""What part of each check's question the evidence did not cover (report 0.4, DECISIONS §99).

A check used to say `pass` whenever it found nothing, even when most of what it was supposed to look
at was never looked at: the first client audits passed STR-4 with 40 of 60 date comparisons not
assessed, and RND-5 on one page of 48. This module reads the evidence each check already records and
lists every part that was not assessed, with a count and the reason. `CheckResult.settle_status`
then turns such a `pass` into `partial`.

It works from evidence rather than from inside each check on purpose: the same function upgrades a
saved 0.3 report (`maya_audit.migrate`), so a live run and a migrated report can never disagree
about what "partial" means.

A part is listed only when a question the check asks could not be answered. Things that are out of
scope by design (a sampled check's unsampled URLs, the spec's own sample) are not parts.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .external_links import REASONS as EXTERNAL_REASONS
from .probes import BROWSER_NOT_REAL_REASON

Part = dict[str, Any]


def part(name: str, reason: str, count: int | None = None, lower_bound: bool = False) -> Part:
    out: Part = {"part": name, "reason": reason}
    if count is not None:
        out["count"] = count
        if lower_bound:
            out["count_is_lower_bound"] = True
    return out


def _count(evidence: dict, list_key: str, count_key: str | None = None) -> tuple[int, bool]:
    """(count, is_lower_bound). Lists in evidence are capped for size; an explicit count key is exact."""
    if count_key and isinstance(evidence.get(count_key), int):
        return evidence[count_key], False
    items = evidence.get(list_key) or []
    n = len(items) if isinstance(items, list) else 0
    return n, n in (20, 40, 60, 100)  # a list exactly at a cap may have been cut


def _listed(evidence: dict, list_key: str, count_key: str | None, name: str, reason: str) -> list[Part]:
    n, lower = _count(evidence, list_key, count_key)
    return [part(name, reason, n, lower)] if n else []


# -- one rule per check ---------------------------------------------------------

def _acc1(ev, obs):
    n = sum(1 for s in ev.get("samples", []) if s.get("status") == 429)
    return [part("robots.txt availability", "robots.txt answered 429; RFC 9309 does not settle how bots treat "
                 "that, and Maya stops on it, so availability is undetermined", n)] if n else []


def _acc4(ev, obs):
    out = []
    unassessed = ev.get("urls_not_assessed") or []
    if ev.get("mode") == "ua_check":  # ownership not verified: a browser and Googlebot only (DECISIONS 205)
        out.append(part("other AI crawlers' user agents", "ownership not verified: only Googlebot's user agent was "
                        "compared with a browser"))
        robots = sum(1 for u in unassessed if str(u.get("reason", "")).startswith("not assessed (robots.txt)"))
        if robots:
            out.append(part("Googlebot user-agent check on sampled URLs", "robots.txt does not allow Googlebot or Maya "
                            "there, so no request was sent", robots))
        unassessed = [u for u in unassessed if not str(u.get("reason", "")).startswith("not assessed (robots.txt)")]
        # The browser itself got an empty or error page (DECISIONS 216): a server fault, not a difference for Googlebot.
        not_real = [u for u in unassessed if u.get("reason") == BROWSER_NOT_REAL_REASON]
        if not_real:
            out.append(part("Googlebot user-agent check on sampled URLs", BROWSER_NOT_REAL_REASON, len(not_real)))
        unassessed = [u for u in unassessed if u.get("reason") != BROWSER_NOT_REAL_REASON]
    if unassessed:
        out.append(part("UA differential on sampled URLs", "the browser baseline itself was blocked, so blocking AI "
                        "bots cannot be told from blocking datacenter traffic", len(unassessed)))
    if ev.get("capped"):
        out.append(part("remaining bot/URL pairs", f"probe cap of {ev.get('cap')} requests reached before every "
                        "pair was probed"))
    return out


def _acc5(ev, obs):
    out = []
    never = ev.get("never_fetched_check")
    if isinstance(never, str) and never.startswith("not assessed"):
        out.append(part("allowed pages never fetched by a verified search bot", never.removeprefix("not assessed: ")))
    unjudged = [o for o in obs if isinstance(o, dict) and str(o.get("threshold", "")).startswith("not set")]
    if unjudged:
        out.append(part("non-2xx share and last-seen per bot", "measured, but the spec sets no threshold yet "
                        "(LG-08), so they are observations, not a judgement", len(unjudged)))
    return out


def _idx1(ev, obs):
    n = sum(1 for o in obs if isinstance(o, dict) and str(o.get("metric", "")).startswith("failure not fetched again"))
    out = [part("persistent vs intermittent failure", "the URL failed once and the refetch cap was reached, so it "
                "was never tried again", n)] if n else []
    probe = ev.get("soft_404_probe")
    if isinstance(probe, dict) and not probe.get("assessed"):
        out.append(part("what a missing page answers (soft 404)", str(probe.get("verdict"))))
    return out


def _idx2(ev, obs):
    n = len(ev.get("not_assessed") or [])
    return [part("TLS / HTTP→HTTPS per host", "; ".join(ev["not_assessed"])[:300], n)] if n else []


def _idx4(ev, obs):
    parts = _listed(ev, "not_assessed", "not_assessed_count", "canonical targets",
                    "the canonical target was not fetched (cap or robots.txt) or is not readable HTML")
    n, lower = _count(ev, "canonical_after_head", "canonical_after_head_count")
    if n:
        # DECISIONS 278: named by element and page, so the release gate can tell "not measured" from "absent".
        parts.append({**part("canonical after an early-closed <head>", "a body element ended <head> before the "
                             "canonical, so the canonical was not read and these pages' canonicals were not judged", n,
                             lower), "element": "canonical", "urls": list(ev.get("canonical_after_head") or [])})
    return parts


# Why a sitemap URL was not checked (DECISIONS 206), when that is a gap. URLs the cap left out are a sample by design,
# and a sitemap check that is off (a single page, sitemap_check_max 0) asks nothing on purpose: neither is a part.
SITEMAP_NOT_CHECKED = {
    "cap": "the lightweight sitemap request cap was reached; remaining listed URLs were not assessed",
    "rate_limit": "the site answered 429 (too many requests), so no further light request was sent",
    "blocked": "the site blocked 3 light requests in a row, so no further one was sent",
    "time_limit": "the audit's time limit was reached before the request could be sent",
    "crawl_stopped": "the crawl stopped early, so no further request was sent",
    "robots_unreadable": "robots.txt could not be read, so Maya makes no further requests to this site",
    "blocked_answer": "the answer was a block, a challenge or a rate limit, so it says nothing about the page",
    "no_answer": "no answer arrived (a timeout or a failed connection)",
    "not_collected": "the sitemap check did not run",
}


# Why a link of llms.txt was not checked (ACC-8, DECISIONS 208). A single-page audit asks for no link on purpose.
# A link to another site goes through the other-site check (DECISIONS 211): its reasons are "external_" + a key of
# maya_audit.external_links.REASONS. "other_site" is for reports saved before that check.
LLMS_NOT_CHECKED = {
    **{k: v for k, v in SITEMAP_NOT_CHECKED.items() if k != "blocked"},
    "blocked_in_a_row": "the site blocked 3 light requests in a row, so no further one was sent",
    "robots": "robots.txt disallows these addresses for Maya's user agent",
    "cap": "the cap of light requests for llms.txt links was reached",
    "other_site": "links to other sites are not checked yet",
    "own_host": "an address on another host of this site, or on a domain of the same brand, is not asked",
    **{f"external_{k}": v for k, v in EXTERNAL_REASONS.items()},
}


def _acc8(ev, obs):
    out = []
    for doc in ev.get("documents") or []:
        name = str(doc.get("url") or "").rsplit("/", 1)[-1]
        for key, count in (((doc.get("links") or {}).get("not_checked")) or {}).items():
            if key in LLMS_NOT_CHECKED and count:
                out.append(part(f"links in {name}", LLMS_NOT_CHECKED[key], count))
    return out


def sitemap_fully_checked(check) -> bool:
    """IDX-5 judged every URL of a usable sitemap through the sitemap check (DECISIONS 206): nothing left unchecked and
    no sample. The crawl's own page cap then leaves no gap in IDX-5's answer."""
    if getattr(check, "check_id", None) != "IDX-5":
        return False
    summary = (check.evidence or {}).get("sitemap_check")
    return bool(summary) and not summary.get("sampled") and not summary.get("not_checked") \
        and not (check.evidence or {}).get("listed_urls_not_fetched")


def _idx5(ev, obs):
    n = ev.get("listed_urls_not_fetched") or 0
    if not n:
        return []
    because = (ev.get("sitemap_check") or {}).get("not_checked_because")
    if because is None:  # a report saved before the sitemap check
        return [part("sitemap-listed URLs", "listed in the sitemap but not fetched by this crawl (page cap, or "
                     "blocked), so their status and indexability are unknown", n)]
    return [part("sitemap-listed URLs", SITEMAP_NOT_CHECKED[key], count) for key, count in because.items()
            if key in SITEMAP_NOT_CHECKED and count]


def _idx7(ev, obs):
    orphans = ev.get("orphans")
    if isinstance(orphans, str) and orphans.startswith("not assessed"):
        return [part("orphan pages", orphans.removeprefix("not assessed: "))]
    return []


def _idx9(ev, obs):
    n = len(ev.get("errors") or [])
    return [part("key-page inspections", "the URL Inspection request failed", n)] if n else []


def _idx10(ev, obs):
    status = ev.get("index_status")
    if isinstance(status, str) and status.startswith("not assessed"):
        return [part("Bing index status", status.removeprefix("not assessed: "))]
    return []


def _rnd1(ev, obs):
    out = []
    if ev.get("render_mode") == "raw_html_only":
        out.append(part("raw vs rendered comparison (T1)", f"rendering did not run ({ev.get('render_reason')}); "
                        "pages were checked with raw-HTML heuristics only, and finding no signal is not "
                        "evidence of no gap"))
    if ev.get("render_failed_pages"):
        out.append(part("rendered pages whose browser check failed",
                        "the render sample includes pages the browser could not inspect; raw HTML heuristics do not replace rendering",
                        ev["render_failed_pages"]))
    if ev.get("third_party_resources_blocked"):
        out.append(part("third-party scripts or resources blocked during rendering",
                        "the browser did not load these resources, so JavaScript content that depends on them may be missing",
                        ev["third_party_resources_blocked"]))
    return out


def _rnd2(ev, obs):
    return _listed(ev, "not_assessed", None, "declared critical facts",
                   "the page was not fetched, or the fact is not in raw text and the page was neither rendered "
                   "nor kept as markup")


def _rnd3(ev, obs):
    out = []
    if not ev.get("rendered_pages"):
        out.append(part("content revealed by interaction (T1)", "no page was rendered, so no click was tried; "
                        "unrendered pages were checked with raw-HTML heuristics only"))
    out += _listed(ev, "text_heuristics_not_assessed", "text_heuristics_not_assessed_count",
                   "'load more' controls on unrendered pages",
                   "the button-text heuristic is English only and these pages are not English")
    return out


def _rnd5(ev, obs):
    n = ev.get("text_signatures_not_assessed_count") or len(ev.get("text_signatures_not_assessed") or [])
    return [part("in-page walls and paywalls", "consent/login/age/geo/paywall text signatures are English only; "
                 "these pages are not English or their language is unknown", n)] if n else []


def _str4(ev, obs):
    return _listed(ev, "not_assessed", "not_assessed_count", "structured-data vs visible comparisons",
                   "the visible side could not be read (no labelled date, or English-only wording on a "
                   "non-English page)")


def _str5(ev, obs):
    out = _listed(ev, "sameAs_not_assessed_or_inconclusive", None, "sameAs profile links",
                   "not fetched (another origin with external link checks off, a cap, or robots.txt) or the "
                   "status was inconclusive (e.g. 403, 999)")
    out += _listed(ev, "localized_name_observations", None, "localized entity names",
                   "Different-language names of the same declared entity require owner confirmation; translation or alias meaning is not established.")
    return out


def _str6(ev, obs):
    out = _listed(ev, "not_assessed", "not_assessed_count", "visible date on article pages",
                  "month names and date labels are read in English only")
    n = ev.get("agreement_not_assessable_pages")
    if n is None and isinstance(ev.get("per_page"), list):  # 0.3 reports: derive from the per-page rows
        rows = ev["per_page"]
        n = sum(1 for r in rows if sum(bool(r.get(k)) for k in ("schema", "visible", "sitemap_lastmod",
                                                                 "last_modified_header")) < 2)
        lower = len(rows) >= 60
    else:
        lower = False
    if n:
        out.append(part("agreement between date signals", "these pages carry fewer than two date signals, so "
                        "there is nothing to compare", n, lower))
    return out


def _str7(ev, obs):
    roles = ev.get('unassessed_image_roles') or []
    instances = {(r.get('url'), r.get('element_id') or r.get('src'), r.get('observed_at'), r.get('source')) for r in roles}
    out = _listed(ev, "excluded_as_rnd1_root_cause", None, "pages with a raw-vs-rendered gap",
                  "RND-1 owns these page-level content gaps, so their images were not reclassified")
    format_scope=ev.get('format_assessment')or{}
    unknown=format_scope.get('delivery_unassessed_resources')
    if isinstance(unknown,int) and unknown:
        out.append(part('image delivery formats', 'No saved successful image response MIME for these unique resources; markup is not delivery evidence.', unknown))
    missing=ev.get('image_format_unassessed_pages')or[]
    if missing:
        out.append(part('source pages missing retained image markup', 'The earlier format finding included these URLs, but eligible image markup is unavailable in the retained page records; they are not passed or reclassified.', len({r['url']for r in missing})))
    if instances:
        out.append(part("unresolved image roles", f"{len(roles)} saved role records represent {len(instances)} distinct page/element/source/time instances; {len({r.get('src') for r in roles if r.get('src')})} source image URLs. Purpose, displayed CSS/pixels and equivalent text require review; neither a pass nor a confirmed missing description.", len(instances)))
    count = ev.get("image_details_not_assessed_count") or 0
    if count:
        out.append(part("image alt details beyond the extraction cap",
                        "the total image and missing-attribute counts are exact, but these images were not retained "
                        "for meaningful/decorative classification", count))
    for reason, n in (ev.get("image_files_not_requested") or {}).items():
        out.append(part("image files not requested", reason, n))
    rest = (ev.get("distinct_content_images") or 0) - (ev.get("image_files_sampled") or 0)
    if rest > 0:
        out.append(part("image files beyond the sample", "only a sample of image files is requested to see whether "
                        "they load (image_checks_max)", rest))
    empty_count = ev.get("empty_alt_not_assessed_count") or 0
    if empty_count:
        out.append(part("images with empty alt text and unknown purpose",
                        "empty alt text is correct for decorative images; without enough markup evidence, Maya could "
                        "not tell whether these images carry information", empty_count))
    return out


def _str9(ev, obs):
    return (_listed(ev, "lang_mismatch_not_assessed", "lang_mismatch_not_assessed_count", "<html lang> vs content "
                    "language", "the language guess was inconclusive or does not cover the declared language")
            + _listed(ev, "hreflang_targets_not_assessed", "hreflang_targets_not_assessed_count", "hreflang targets",
                      "the target was not fetched (another origin, cap, or robots.txt) or failed")
            + _listed(ev, "hreflang_target_pages_not_read", "hreflang_target_pages_not_read_count",
                      "hreflang target pages (title, description, noindex, canonical)",
                      "the target answered but was not crawled, so its page was not read"))


def _str10(ev, obs):
    return _listed(ev, "og_image_not_assessed_or_inconclusive", "og_image_not_assessed_count", "og:image URLs",
                   "not fetched (another origin with external link checks off, a cap, or robots.txt) or the "
                   "status was inconclusive")


def _str11(ev, obs):
    return _listed(ev, "unparseable_jsonld_pages", "unparseable_jsonld_pages_count", "structured data in JSON-LD "
                   "that does not parse", "a block that does not parse cannot be compared with the page's other "
                   "descriptions (STR-3 reports the parse error)") + _listed(
                       ev, "date_precision_not_assessed", "date_precision_not_assessed_count",
                       "same-event dates with mixed precision", "the date-only timezone is unknown; an adjacent UTC day does not establish a contradiction")


def _str12(ev, obs):
    return _listed(ev, "language_not_assessed", "language_not_assessed_count", "content language of pages",
                   "the page declares no supported language, or has too little main content to tell")


def _left_out(reason: str):
    def rule(ev, obs):
        n = ev.get("pages_left_out_count") or 0
        detail = "; ".join(f"{count} {why}" for why, count in (ev.get("pages_left_out") or {}).items())
        return [part("pages left out of this comparison", f"{reason} ({detail})", n)] if n else []
    return rule


_str16 = _left_out("a shared description on these pages could not be judged fairly")
_str17 = _left_out("whether these pages lead on could not be told from their HTML, or they end by design")


_str20 = _left_out("their own text arrives only after JavaScript runs, so its length could not be judged")


def _tseo1(ev, obs):
    out = []
    excluded = ev.get("excluded_pages_count") or 0
    if excluded:
        out.append(part("pages excluded for incomplete raw HTML",
                        "rendering-gap pages or truncated responses were not treated as clean", excluded))
    if ev.get("crawl_incomplete"):
        count = ev.get("not_fetched_url_count") or 0
        out.append(part("discovered pages not fetched",
                        f"the crawl stopped at {ev.get('crawl_stop_reason')}; their metadata and headings were not read",
                        count))
    return out


def _prf1(ev, obs):
    return _listed(ev, "not_enough_samples", "not_enough_samples_count", "response time of sampled URLs",
                   "fewer successful samples than the minimum needed to judge")


def _ans1(ev, obs):
    out = []
    completeness = ev.get("input_completeness")
    if isinstance(completeness, str) and completeness.startswith("incomplete"):
        out.append(part("citations of this site", completeness.removeprefix("incomplete: ")))
    # 0.4 lists exactly the cited URLs nothing was learned about; a 0.3 report only has the unfetched ones,
    # some of which a robots.txt block still turned into findings, so that count can overstate.
    unchecked = ev.get("cited_urls_not_checked")
    n = len(unchecked if unchecked is not None else ev.get("cited_url_fetches") or [])
    if n:
        out.append(part("cited URLs the crawl did not cover", "not fetched (cap, or robots.txt disallows Maya's "
                        "user agent), or the site answered Maya with a block or bot challenge, so their health is "
                        "unknown; the reason per URL is in cited_urls_not_checked", n))
    unresolved = len(ev.get("cited_urls_with_unresolved_handoff") or [])
    if unresolved:
        out.append(part("where redirected or canonicalized cited URLs land", "a hop in the redirect or canonical "
                        "chain was not fetched (cap or robots.txt), so the landing page was not judged", unresolved))
    edge = ev.get("edge_blocking_not_assessed_count") or 0
    if edge:
        out.append(part("edge blocking of cited URLs (ACC-4)", "these cited URLs were not probed with AI-bot user "
                        "agents (ownership not verified, or not in the probe sample); robots.txt rules cannot show "
                        "WAF or edge blocks", edge))
    return out


def _ans2(ev, obs):
    n = ev.get("records_without_a_readable_cited_page") or 0
    return [part("claims in answers citing an unreadable page", "the cited page was not readable HTML, so its "
                 "claims could not be compared", n)] if n else []


def _str2(ev, obs):
    return (_listed(ev, "h1_cut_off", "h1_cut_off_count", "pages whose HTML was cut off before an <h1>",
                    "the page's HTML was longer than the fetch-size limit and no <h1> appeared before the cut, so whether "
                    "it has one is unknown")
            # DECISIONS 283 (8): the homepage outline and the long-page check on a cut body.
            + _listed(ev, "sections_cut_off", "sections_cut_off_count",
                      "pages whose HTML was cut off before their section headings could be counted",
                      "the page's HTML was longer than the fetch-size limit and too few <h2>/<h3> appeared before the cut; "
                      "the rest of the page may have them, so whether it is sectioned is unknown"))


def _str8(ev, obs):
    return _listed(ev, "table_semantics_unassessed", None, "data-table header relationships",
                   "saved HTML does not establish table purpose or complete header associations")


def _rnd4(ev,obs):
    return _listed(ev,'iframe_names_unassessed',None,'iframe accessible names',
                   'saved evidence does not include a complete accessible-name assessment')


RULES: dict[str, Callable[[dict, list], list[Part]]] = {
    "ACC-1": _acc1, "ACC-4": _acc4, "ACC-5": _acc5, "ACC-8": _acc8,
    "IDX-1": _idx1, "IDX-2": _idx2, "IDX-4": _idx4, "IDX-5": _idx5, "IDX-7": _idx7, "IDX-9": _idx9,
    "IDX-10": _idx10,
    "RND-1": _rnd1, "RND-2": _rnd2, "RND-3": _rnd3, "RND-4": _rnd4, "RND-5": _rnd5,
    "STR-2": _str2, "STR-4": _str4, "STR-5": _str5, "STR-6": _str6, "STR-7": _str7, "STR-8": _str8, "STR-9": _str9,
    "STR-10": _str10, "STR-11": _str11, "STR-12": _str12, "STR-16": _str16, "STR-17": _str17, "STR-20": _str20,
    "TSEO-1": _tseo1,
    "PRF-1": _prf1,
    "ANS-1": _ans1, "ANS-2": _ans2,
}
# Checks whose output is measurement only: nothing to pass or fail (spec: ANS-5 produces observations).
OBSERVATION_ONLY = frozenset({"ANS-5"})


def derive(check_id: str, status: str, evidence: dict, observations: list) -> dict[str, Any]:
    """Coverage for one check. A check already `not_assessed` as a whole has no parts to list."""
    rule = RULES.get(check_id)
    parts = rule(evidence or {}, observations or []) if rule and status != "not_assessed" else []
    return {"not_assessed": parts, "rule": "derived from this check's recorded evidence (maya_audit.coverage)"}


# Checks whose question is answered by reading the audited pages. When Maya could read none of them (every page
# blocked or rate-limited, INT-1), they found nothing because they looked at nothing: that is Not assessed, never
# a pass. Seen live on 2026-09-22: a site answering every request with a Cloudflare challenge came back with
# IDX-1 "no 4xx ... across 0 fetched URLs" and nine other checks marked PASS.
PAGE_DEPENDENT = frozenset({"ACC-3", "IDX-1", "IDX-3", "IDX-4", "IDX-5", "IDX-6", "IDX-7", "IDX-8",
                            *(f"RND-{i}" for i in range(1, 8)), *(f"STR-{i}" for i in range(1, 24)), "TSEO-1",
                            "PRF-1", "PRF-2"})


def page_access(pages) -> dict[str, int]:
    """How many fetched pages Maya could read, from PageFetch objects or a saved report's page dicts."""
    def get(page, key):
        return page.get(key) if isinstance(page, dict) else getattr(page, key)

    def cls(page):
        value = get(page, "fetch_class")
        return getattr(value, "value", value)

    fetched = len(pages)
    impaired = sum(1 for p in pages if cls(p) in ("blocked", "rate_limited"))
    readable = sum(1 for p in pages if get(p, "content_checks_eligible") and get(p, "analysis") is not None)
    return {"fetched": fetched, "impaired": impaired, "readable": readable}


def _access_part(access: dict | None) -> list[Part]:
    if not access or not access["impaired"]:
        return []
    return [part("pages Maya was blocked or rate-limited on (INT-1)", "the site answered Maya's crawler with a "
                 "block, a bot challenge, or a rate limit, so these pages' content was never read",
                 access["impaired"])]


# Checks that read the content of indexable pages (the same list as maya_audit.firecrawl.reader.CONTENT_CHECKS). With
# no such page to look at, "nothing found" is not a pass (DECISIONS 168). Seen on 2026-10-11: a site whose 50 pages
# were all read as noindex came back with "No news or press page among the pages read" and four more clean results.
NEEDS_AN_INDEXABLE_PAGE = frozenset({"IDX-8", *(f"STR-{i}" for i in range(1, 24)), "TSEO-1"})
NONE_INDEXABLE = "all are noindex or canonical to another address"
NONE_WITH_CONTENT = "all were withheld because their content arrives after JavaScript"


def looked_at_no_page(check, indexable: int | None) -> str | None:
    """Why a check of page content had no page to look at, or None when it had one. Read from the audit's count of
    indexable pages and from what the check itself recorded (`pages_checked`, `candidates`)."""
    evidence = check.evidence or {}
    if not (indexable == 0 or evidence.get("pages_checked") == 0 or evidence.get("candidates") == 0):
        return None
    return NONE_WITH_CONTENT if indexable or evidence.get("excluded_as_rnd1_root_cause") else NONE_INDEXABLE


def settle(check, access: dict | None = None, crawl_gap: Part | None = None, indexable: int | None = None) -> None:
    """Attach coverage to a CheckResult and let it correct its own status. `indexable` is how many indexable pages
    the audit has (maya_audit.structure_data.indexable_pages), when the caller knows."""
    check.coverage = derive(check.check_id, check.status, check.evidence, check.observations)
    from .evidence_accuracy import check_scope, probe_scope_recorded
    assessment = check_scope(check.check_id, check.evidence or {})
    if assessment: check.evidence = {**(check.evidence or {}), 'assessment_scope': assessment}
    if check.check_id in PAGE_DEPENDENT and check.status != "not_assessed":
        check.coverage["not_assessed"] = _access_part(access) + check.coverage["not_assessed"]
        # A sitemap check that judged every sitemap URL needs no page the crawl left unread.
        if crawl_gap and not probe_scope_recorded(check.check_id, check.evidence or {}) and not sitemap_fully_checked(check):
            check.coverage["not_assessed"].append(crawl_gap)
        elif crawl_gap and crawl_gap.get("count") and check.check_id == "IDX-1":
            # IDX-1 judges the answers Maya's crawler received (its own scope), and an address the crawl found and
            # did not fetch has no answer here: it may be the broken one. Unknown, never "no 4xx" (DECISIONS 280, 282).
            check.coverage["not_assessed"].append(part(
                "addresses found but not fetched by the crawl", "these addresses were found but the crawl did not fetch "
                "them, so this check has no answer for them; another step, such as the sitemap check, may have requested "
                "some", crawl_gap["count"]))
        if access and access["fetched"] and not access["readable"] and check.status in ("pass", "partial", "not_applicable"):
            check.status = "not_assessed"
            check.summary = (f"Not assessed: Maya could read none of the {access['fetched']} page(s) it fetched "
                             f"({access['impaired']} blocked or rate-limited; see INT-1), so there was nothing to "
                             f"check. (Before this: {check.summary})")
            return
    if check.check_id in NEEDS_AN_INDEXABLE_PAGE and check.status in ("pass", "partial", "observed", "not_applicable") and not check.findings:
        why = looked_at_no_page(check, indexable)
        if why:
            read = (access or {}).get("readable") or 0
            check.status = "not_assessed"
            check.coverage["not_assessed"] = []  # the whole check is not assessed: there are no parts to list
            check.summary = (f"Not assessed: none of the {read} pages read could be checked ({why}), so there was nothing to look at."
                             if read else "Not assessed: no page that could be checked was read, so there was nothing to look at.")
            return
    if check.check_id in OBSERVATION_ONLY and check.status == "pass":
        check.status = "observed"
    check.settle_status()


# The part every page-reading check gets when the crawl did not read everything it found. One fact about the
# audit, repeated on each check so that no check's clean result is read as covering the whole site; a reader
# showing coverage to a person should say it once (see CRAWL_GAP_NAMES).
PROBE_SCOPED = frozenset({"IDX-1", "IDX-2", "IDX-5", "IDX-6", "PRF-1", "PRF-2"})
CRAWL_GAP = "pages found but not read"
CRAWL_GAP_NAMES = frozenset({CRAWL_GAP, "pages not checked because the crawl was incomplete"})  # the second: reports before 2026-10-07


def crawl_gap_part(read: int, unread: int, detail: str) -> Part:
    return part(CRAWL_GAP,
                f"this check ran on the {read} page(s) that were read"
                + (f"; {unread} more page(s) were found and not read" if unread else "")
                + f" ({detail}). Its result says nothing about pages that were not read",
                unread if unread else None)


# -- a check that found nothing in what was read, when not everything was read (decision 189) --------------------------
#
# Such a check is `partial`, never a pass (decision 99), and so it used to appear only under "What could not be
# checked". What it did find out is worth one sentence where the checks in order are listed: "No problem found on the
# 50 pages read (9 not read)". The check stays partial and stays listed among what could not be checked.
#
# A check that had nothing to look at does not get the sentence. Where its evidence counts what it looked at, a zero
# there says so: for any check `pages_checked` and `candidates` (decision 168), and for the checks below the count
# their question depends on (every count named must be zero). STR-22 and STR-23 "found nothing" among pages of which
# none was a news or a job page: nothing was compared, so they say their own summary only.
NOTHING_LOOKED_AT = ("pages_checked", "candidates")
NOTHING_COMPARED = {
    "RND-2": ("declared_facts",),                              # "All 0 declared fact(s) are in raw HTML"
    "STR-16": ("pages_compared",),                             # "... between the 0 page(s) compared"
    "STR-22": ("news_pages",),                                 # "No news or press page among the pages read"
    "STR-23": ("job_pages", "careers_pages_listing_openings"),
    "PRF-1": ("sample_size",),
    "PRF-2": ("attempts_counted",),
}
# The same said by a summary whose check recorded no such count (a report saved by an earlier engine).
_ZERO_IN_SUMMARY = re.compile(r"\b(?:all|the|on|across|among|of the) 0 [a-z]", re.IGNORECASE)
# TSEO-1 counts the addresses that were not read in a part of its own.
_GAP_PARTS = {"TSEO-1": frozenset({"discovered pages not fetched"})}


def clean_on_what_was_read(check) -> bool:
    """Whether `check` (a CheckResult, or a check of a saved report) found nothing on the pages that were read and is
    partial only because some pages found were not read. Decided from what the report holds, so a saved report
    gives the same answer as a new one."""
    def get(key, default=None):
        return check.get(key, default) if isinstance(check, dict) else getattr(check, key, default)

    check_id = get("check_id")
    if check_id not in PAGE_DEPENDENT or get("status") != "partial" or get("findings") or get("review_items"):
        return False
    parts = (get("coverage") or {}).get("not_assessed") or []
    allowed = CRAWL_GAP_NAMES | _GAP_PARTS.get(check_id, frozenset())
    if not any(part.get("part") in CRAWL_GAP_NAMES for part in parts) or any(part.get("part") not in allowed for part in parts):
        return False
    evidence = get("evidence") or {}
    if any(evidence.get(key) == 0 for key in NOTHING_LOOKED_AT):
        return False
    counts = NOTHING_COMPARED.get(check_id)
    if counts and all(evidence.get(key) == 0 for key in counts):
        return False
    return not _ZERO_IN_SUMMARY.search(get("summary") or "")


_GAP_DETAIL = re.compile(r" \((?P<detail>.+)\)\. Its result says nothing about pages that were not read$", re.DOTALL)
# TSEO-1 counts the same addresses in a part of its own.
_SAME_FIGURE = frozenset({"discovered pages not fetched"})


def restated(parts: list[Part], read: int, unread: int) -> list[Part]:
    """`parts` with every "pages found but not read" part saying `read` pages read and `unread` addresses not read.
    The reason the crawl gave is kept. A new list; the parts handed in are not changed."""
    out = []
    for old in parts or []:
        if old.get("part") in CRAWL_GAP_NAMES:
            found = _GAP_DETAIL.search(old.get("reason") or "")
            out.append(crawl_gap_part(read, unread, found.group("detail") if found else "the crawl did not read every address it found"))
        elif old.get("part") in _SAME_FIGURE and "count" in old:
            out.append({**old, "count": unread})
        else:
            out.append(old)
    return out


def restate_crawl_gap(checks: list, read: int, unread: int) -> None:
    """One "not read" figure for the whole report (DECISIONS 170). Each check's "pages found but not read" part was
    written from Maya's own crawl, before a page reader read more of the site and left out what is not a page. When
    the final list of checks is assembled, every such part is rewritten with the report's own figures: `read` pages
    read, `unread` addresses known and not read (`report.read_counts`, `report.known_unread`). A check with no such
    part is left as it is. (A saved report is restated the same way when it is displayed: `restated`.)"""
    for check in checks:
        coverage = getattr(check, "coverage", None) or {}
        from .evidence_accuracy import probe_scope_recorded
        if probe_scope_recorded(check.check_id, check.evidence or {}):
            coverage["not_assessed"] = [p for p in coverage.get("not_assessed", []) if p.get("part") not in CRAWL_GAP_NAMES]
        if coverage.get("not_assessed"):
            coverage["not_assessed"] = restated(coverage["not_assessed"], read, unread)


def settle_all(checks: list, result=None) -> list:
    access = page_access(result.pages) if result is not None and getattr(result, "pages", None) is not None else None
    crawl_gap = None
    if result is not None:
        reason = getattr(getattr(result, "stop_reason", None), "value", getattr(result, "stop_reason", None))
        unfetched = len(getattr(result, "not_fetched_urls", []) or [])
        deadline_hit = bool(getattr(result, "deadline_hit", False))
        if reason != "exhausted" or unfetched or deadline_hit:
            detail = getattr(result, "stop_detail", "") or f"crawl stopped with reason {reason}"
            if deadline_hit:
                detail = (getattr(result, "collector_errors", {}).get("audit_deadline")
                          or "overall audit deadline reached during post-crawl checks")
            read = sum(1 for page in (getattr(result, "pages", None) or [])
                       if not (getattr(page, "status", None) is not None and 300 <= page.status < 400))
            # The check ran. What it could not speak for is the pages nobody read. (The earlier wording, "pages not
            # checked because the crawl was incomplete", read as if the check itself had not run.)
            crawl_gap = crawl_gap_part(read, unfetched, detail)
    indexable = None
    if getattr(result, "pages", None) is not None and any(check.check_id in NEEDS_AN_INDEXABLE_PAGE for check in checks):
        from .structure_data import indexable_pages  # here: that module's imports reach back to the checks

        indexable = len(indexable_pages(result))
    for check in checks:
        settle(check, access, crawl_gap, indexable)
        if result is not None and (check.check_id.startswith("STR-") or check.check_id == "TSEO-1"):
            truncated = sum(1 for page in (getattr(result, "pages", []) or [])
                            if getattr(page, "body_truncated", False))
            if truncated and check.status != "not_assessed":
                check.coverage.setdefault("not_assessed", []).append(
                    part("truncated page bodies", "some HTML bodies exceeded the fetch-size limit, so checks of "
                         "their full source may have missed content", truncated))
                check.settle_status()
    return checks
