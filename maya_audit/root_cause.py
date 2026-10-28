"""One cause, one finding: problems that several checks report about the same pages are said once (DECISIONS 215, 225).

`group(checks, result)` runs once the checks are built (`audit.run_audit`, just before `launch_gate.apply`) and again
after a page reader replaced the content checks (`firecrawl.reader.apply`). It changes nothing twice.

Empty and failing pages (DECISIONS 215). IDX-1 reports the pages that answer with an empty page or print a server error
message ("E"). The same addresses are often in the sitemap (IDX-5) and in llms.txt (ACC-8):
- IDX-5 keeps its share and its threshold, both counted with E. E is taken out of the finding's scope, and its title
  starts with the URLs left (the number its scope gives, review CR-28) and says how many more are IDX-1's. When the share without E is at or under the threshold, the finding
  is left out and IDX-1 says so.
- ACC-8 leaves E out of the finding and says how many of the links lead to IDX-1's pages; with only E left, the
  finding is left out.
- IDX-1 says where else its pages are listed (`evidence.also_listed_in`) and in which sections they are
  (`evidence.by_section`).

Copies and near-copies (DECISIONS 225, amends 187). IDX-8's groups of identical and of nearly identical pages become
one IDX-8 finding with a line for each group. A group of STR-1 (shared title) or STR-16 (shared meta description) whose
pages all fall inside one duplicate group is said on that group's line; STR-1 and STR-16 keep their other groups, or
are left out with a note in their summary when none is left. A merged finding keeps the launch-gate items of the
findings it was made from.

Dead internal link targets (review H10, CR-03). IDX-1 reports a 4xx URL that is linked or listed; IDX-6 reported each
such target again, one finding per target (DECISIONS 20). The IDX-6 findings whose target is in IDX-1's 4xx finding are
folded into it: its title says how many pages link to the dead URLs, and its evidence keeps one row per target with the
pages that link to it (`broken_links`), so DECISIONS 20's one task per dead URL is still in the data. IDX-6 says in its
summary how many targets it left to IDX-1.

Drafts and second addresses (review H13, H20). A draft or test page in the sitemap is IDX-5's finding, and a page reached
at two addresses (/UyeGiris and /UyeGiris.aspx) is IDX-8's: STR-1 does not count a draft among the pages with no title,
nor STR-15 among the short pages, and STR-1 and STR-16 do not count a page's second address as another page sharing
its title or description.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

from .checks.access import IDX1_SUFFIX as ACC8_SUFFIX
from .checks.index import (BROKEN_TARGET_TITLE, DRAFT_TITLE, IDX1_BESIDE, IDX6_SUFFIX, REFERENCED_4XX_TITLE, SHARE_TITLE,
                           TWO_ADDRESSES_TITLE, idx8_merged)
from .findings import Finding, scope_for

MARK = "_root_cause"  # in a check's evidence: what this module did, so a second run changes nothing twice

EMPTY_TITLE = re.compile(r"answer with an empty page|show a server error message")
IDX5_SHARE = re.compile(r"are not live, indexable pages")
ACC8_LINKS = re.compile(r"lead to pages that do not work")
ACC4_GOOGLEBOT = re.compile(r"Googlebot's user agent")
IDX5_LEFT_OUT = ("The sitemap share is reported under IDX-1: without the {same} empty or failing page(s) IDX-1 reports, "
                 "{rest} of {assessed} sitemap URL(s) checked are not live, which is within the threshold.")

# IDX-8, merged.
EXACT_TITLE = re.compile(r"have identical visible text")
NEAR_TITLE = re.compile(r"have nearly identical main content")
STR1_TITLE = re.compile(r"^(?P<n>\d+) title\(s\) are shared by (?P<pages>\d+) different indexable pages")
STR16_TITLE = re.compile(r"^(?P<n>\d+) meta description\(s\) are shared by (?P<pages>\d+) different indexable pages")
STR1_LEFT_OUT = "{n} shared title(s) are said with the copies and near-copies under IDX-8."
STR16_LEFT_OUT = "{n} shared meta description(s) are said with the copies and near-copies under IDX-8."


def group(checks: list[Any], result: Any) -> None:
    """Say each cause once, in place. Does nothing twice."""
    by_id = {check.check_id: check for check in checks}
    from .related_evidence import objects
    objects(checks, result, sitemaps=False)
    _empty_pages(by_id, result)
    _broken_targets(by_id)
    _said_elsewhere(by_id)
    _duplicates(by_id)
    _head_closed(by_id, result)


# -- empty and failing pages ---------------------------------------------------------------------------------------------

def _urls(finding: Finding) -> list[str]:
    return list(finding.scope.get("_all_urls") or finding.scope.get("urls") or [])


def _renamed(finding: Finding) -> None:
    """A new id for a finding whose title or pages changed (the id is made from both)."""
    finding.id = ""
    finding.__post_init__()


def _settle(check: Any, sentence: str) -> None:
    """A check whose finding was left out: the sentence is said in its summary, and its status follows."""
    check.summary = f"{(check.summary or '').strip()} {sentence}".strip()
    if not check.findings and check.status == "findings":
        check.status = "needs_review" if check.review_items else "pass"
        check.settle_status()


def _path(url: str) -> str:
    parts = urlsplit(url)
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def by_section(urls: list[str]) -> list[dict[str, Any]]:
    """The pages by the first part of their path ("/semt/"), most first, with up to three examples each."""
    sections: dict[str, list[str]] = {}
    for url in urls:
        first = urlsplit(url).path.strip("/").split("/", 1)[0]
        sections.setdefault(f"/{first}/" if first else "/", []).append(url)
    return [{"section": section, "count": len(pages), "examples": [_path(u) for u in pages[:3]]}
            for section, pages in sorted(sections.items(), key=lambda item: (-len(item[1]), item[0]))]


def _threshold(result: Any) -> float:
    try:
        return float((getattr(result, "config", None) or {}).get("sitemap_bad_share", 0.10))
    except (TypeError, ValueError):
        return 0.10


def _idx5(check: Any, empty: set[str], result: Any) -> dict[str, Any] | None:
    """Take IDX-1's pages out of IDX-5's share finding (once). What was done: {"urls", "finding_id", "left_out"}."""
    done = (check.evidence or {}).get(MARK)
    if done is not None:
        return done
    finding = next((f for f in check.findings if IDX5_SHARE.search(f.title)), None)
    if finding is None:
        return None
    bad = _urls(finding)
    from .evidence_accuracy import membership
    known, complete = membership({'scope':finding.scope,'evidence':finding.evidence})
    finding.evidence['membership_assessment'] = {'known_urls':known,'complete':complete,'declared_count':finding.scope.get('count')}
    if not complete:
        check.evidence['overlap_unassessed'] = {'reason':'Complete sitemap finding membership was not retained; samples cannot establish exact overlap or remaining counts.', 'known_urls':known}
        return None
    from .judgments import sitemap_states
    states=finding.evidence.get('sitemap_decisions') or sitemap_states(result)
    independent={r['url']for r in states if r.get('state')in ('redirect_observed','noindex_observed','contradictory')}
    same = [url for url in bad if url in empty and url not in independent]
    if not same:
        check.evidence = {**(check.evidence or {}), MARK: {"urls": [], "finding_id": finding.id, "left_out": False}}
        return check.evidence[MARK]
    rest = [url for url in bad if url not in same]
    # Retain the complete original review record even when no second repair remains.
    from .models import to_jsonable
    check.evidence.setdefault('retrieval_overlap',{
        'finding':deepcopy(to_jsonable(finding)),
        'total_review_scope':{'count':len(bad),'urls':list(bad)},
        'reported_under_idx1':{'count':len(same),'examples':list(same)}})
    assessed = int(finding.evidence.get("listed_urls_assessed") or len(bad) or 1)
    # Keep owner/indexing and conflicting-evidence decisions from being erased by
    # the new HTTP overlap. Preserve the existing below-threshold redirect policy.
    decisions={r['url']for r in states if r.get('state')in ('noindex_observed','contradictory')}
    if len(rest) / assessed <= _threshold(result) and not any(u in decisions for u in rest):
        check.findings = [f for f in check.findings if f is not finding]
        _settle(check, IDX5_LEFT_OUT.format(same=len(same), rest=len(rest), assessed=assessed))
        done = {"urls": same, "finding_id": None, "left_out": True}
    else:
        parts = SHARE_TITLE.match(finding.title)
        if parts:
            finding.title = IDX1_BESIDE.format(rest=len(rest), assessed=parts["assessed"], checked=parts["checked"] or "",
                                               same=len(same), share=parts["share"], tail=parts["tail"])
        finding.scope = scope_for(rest)
        finding.evidence = {**finding.evidence,
                            "original_bad_urls": finding.evidence.get("original_bad_urls", finding.evidence.get("bad_urls") or []),
                            "bad_urls": [row for row in finding.evidence.get("bad_urls") or [] if row.get("url") not in same],
                            "reported_under_idx1": {"count": len(same), "examples": same[:10],
                                                    "why": "empty or failing pages: IDX-1 reports them; they stay in the share"}}
        _renamed(finding)
        done = {"urls": same, "finding_id": finding.id, "left_out": False}
    check.evidence = {**(check.evidence or {}), MARK: done}
    return done


def _acc8(check: Any, empty: set[str]) -> dict[str, dict[str, Any]]:
    """Take IDX-1's pages out of ACC-8's link findings (once). By file name: {"urls", "finding_id"}."""
    done = (check.evidence or {}).get(MARK)
    if done is not None:
        return done
    done = {}
    for finding in list(check.findings):
        if not ACC8_LINKS.search(finding.title):
            continue
        links = finding.evidence.get("links") or {}
        bad = list(links.get("not_working_urls") or [row.get("url") for row in finding.evidence.get("not_working") or []])
        same = [url for url in bad if url in empty]
        name = str(finding.evidence.get("file") or "llms.txt").rsplit("/", 1)[-1]
        if not same:
            continue
        rest = [url for url in bad if url not in empty]
        if not rest:
            # Said by IDX-1's own line ("Also linked from llms.txt"); the presence finding stays, so the status does too.
            check.findings = [f for f in check.findings if f is not finding]
            done[name] = {"urls": same, "finding_id": None}
            continue
        finding.title += ACC8_SUFFIX.format(same=len(same))
        finding.evidence = {**finding.evidence,
                            "not_working": [row for row in finding.evidence.get("not_working") or [] if row.get("url") not in empty],
                            "reported_under_idx1": {"count": len(same), "examples": same[:10]}}
        _renamed(finding)
        done[name] = {"urls": same, "finding_id": finding.id}
    check.evidence = {**(check.evidence or {}), MARK: done}
    return done


def _empty_pages(by_id: dict[str, Any], result: Any) -> None:
    idx1 = by_id.get("IDX-1")
    if idx1 is None:
        return
    from .related_evidence import retrieval_urls
    represented={f.id:retrieval_urls({'check_id':f.check_id,'title':f.title,'severity':f.severity,'confidence':f.confidence,'scope':f.scope,'evidence':f.evidence})for f in idx1.findings}
    reported = [f for f in idx1.findings if represented[f.id]]
    empty = set().union(*(represented[f.id]for f in reported))if reported else set()
    if not empty:
        return
    sitemap = by_id.get("IDX-5")
    idx5 = _idx5(sitemap, empty, result) if sitemap is not None else None
    # The requested HTTP-error expansion belongs to sitemap overlap. Preserve
    # ACC-8's existing empty/server-message grouping boundary.
    llms_empty={u for f in reported if EMPTY_TITLE.search(f.title)for u in represented[f.id]}
    llms = _acc8(by_id["ACC-8"], llms_empty) if "ACC-8" in by_id else {}
    googlebot = [f for f in (by_id["ACC-4"].findings if "ACC-4" in by_id else []) if ACC4_GOOGLEBOT.search(f.title)]
    listed = set(getattr(result, "sitemap_urls", None) or [])
    for finding in reported:
        mine = _urls(finding)
        also: list[dict[str, Any]] = []
        if idx5 and idx5.get("urls"):
            count = sum(1 for url in mine if url in set(idx5["urls"]))
            if count:
                also.append({"where": "sitemap", "count": count, "finding_id": idx5["finding_id"],
                             **({"left_out": True} if idx5.get("left_out") else {})})
        else:
            count = sum(1 for url in mine if url in listed)
            if count:
                also.append({"where": "sitemap", "count": count, "finding_id": None, "not_in_share_finding": True})
        for name, entry in llms.items():
            count = sum(1 for url in mine if url in set(entry["urls"]))
            if count:
                also.append({"where": "llms.txt", "file": name, "count": count, "finding_id": entry["finding_id"]})
        for other in googlebot:
            count = sum(1 for url in mine if url in set(_urls(other)))
            if count:
                also.append({"where": "acc4", "count": count, "finding_id": other.id})
        evidence = {key: value for key, value in finding.evidence.items() if key not in ("also_listed_in", "by_section")}
        if also:
            evidence["also_listed_in"] = also
        if len(mine) >= 2:
            evidence["by_section"] = by_section(mine)
        finding.evidence = evidence


# -- dead internal link targets -----------------------------------------------------------------------------------------

IDX6_LEFT_OUT = "{n} broken target(s) are said under IDX-1, with the pages that link to them."


def _broken_targets(by_id: dict[str, Any]) -> None:
    """Fold IDX-6's per-target findings into IDX-1's 4xx finding when IDX-1 reports the same dead URLs (once)."""
    idx1, idx6 = by_id.get("IDX-1"), by_id.get("IDX-6")
    if idx1 is None or idx6 is None or (idx6.evidence or {}).get(MARK) is not None:
        return
    referenced = next((f for f in idx1.findings if REFERENCED_4XX_TITLE.search(f.title)), None)
    dead = set(_urls(referenced)) if referenced is not None else set()
    moved = [f for f in idx6.findings if BROKEN_TARGET_TITLE.search(f.title) and (f.evidence or {}).get("target") in dead]
    idx6.evidence = {**(idx6.evidence or {}), MARK: {"targets": [], "finding_id": None}}
    if not moved:
        return
    rows = [{"target": f.evidence["target"], "status": f.evidence.get("target_status"),
             "linked_from_count": len(_urls(f)), "links": (f.evidence.get("links") or [])[:40]} for f in moved]
    sources = list(dict.fromkeys(url for f in moved for url in _urls(f)))
    idx6.findings = [f for f in idx6.findings if f not in moved]
    referenced.title += IDX6_SUFFIX.format(pages=len(sources))
    referenced.evidence = {**referenced.evidence, "broken_links": rows[:40], "broken_links_count": len(rows),
                           "linked_from_count": len(sources), "linked_from": sources[:40],
                           "said_once": "IDX-6 found these dead targets too; its one finding per dead URL is a row here"}
    referenced.importance_tier = min([referenced.importance_tier, *(f.importance_tier for f in moved)])
    _renamed(referenced)
    idx6.evidence[MARK] = {"targets": [row["target"] for row in rows], "finding_id": referenced.id}
    _settle(idx6, IDX6_LEFT_OUT.format(n=len(rows)))


# -- drafts and second addresses -----------------------------------------------------------------------------------------

SAID = "_said_elsewhere"  # in STR-1's or STR-16's evidence: done; a page reader's new STR checks are done again
NO_TITLE = re.compile(r"^(?P<n>\d+) page\(s\) have no <title>")
THIN = re.compile(r"^(?P<n>\d+) content page\(s\) have fewer than")
QA_BLOCK = re.compile(r"^(?P<n>\d+) page\(s\) show questions and answers")
STR1_DRAFTS_LEFT_OUT = "{n} page(s) without a title are the draft or test pages reported under IDX-5."
STR15_DRAFTS_LEFT_OUT = "{n} short page(s) are the draft or test pages reported under IDX-5."
STR3_DRAFTS_LEFT_OUT = "{n} page(s) with questions and answers are the draft or test pages reported under IDX-5."
STR1_ALIASES_LEFT_OUT = "{n} shared title(s) are one page at two addresses, reported under IDX-8."
STR16_ALIASES_LEFT_OUT = "{n} shared meta description(s) are one page at two addresses, reported under IDX-8."


def _drafts_and_aliases(by_id: dict[str, Any]) -> tuple[set[str], dict[str, str]]:
    """The draft pages IDX-5 reports, and IDX-8's second addresses ({other: kept})."""
    drafts: set[str] = set()
    for finding in (by_id["IDX-5"].findings if "IDX-5" in by_id else []):
        if DRAFT_TITLE.search(finding.title):
            drafts |= set(finding.evidence.get("draft_urls") or _urls(finding))
    aliases: dict[str, str] = {}
    for finding in (by_id["IDX-8"].findings if "IDX-8" in by_id else []):
        if TWO_ADDRESSES_TITLE.search(finding.title):
            aliases.update({pair["other"]: pair["kept"] for pair in finding.evidence.get("pairs") or []})
    return drafts, aliases


def _without_drafts(check: Any, drafts: set[str], pattern: re.Pattern, left_out: str) -> None:
    """STR-1's pages with no title, and STR-15's short pages, lose the drafts IDX-5 reports."""
    finding = next((f for f in check.findings if pattern.search(f.title)), None)
    if finding is None:
        return
    gone = [url for url in _urls(finding) if url in drafts]
    if not gone:
        return
    rest = [url for url in _urls(finding) if url not in drafts]
    sentence = left_out.format(n=len(gone))
    if not rest:
        check.findings = [f for f in check.findings if f is not finding]
        _settle(check, sentence)
        return
    match = pattern.search(finding.title)
    finding.title = f"{len(rest)}{finding.title[match.end('n'):]}"
    finding.scope = scope_for(rest)
    pages = [row for row in finding.evidence.get("pages") or []
             if (row.get("url") if isinstance(row, dict) else row) not in drafts]
    finding.evidence = {**finding.evidence, "pages": pages, **({"count": len(rest)} if "count" in finding.evidence else {}),
                        "said_under_idx5": len(gone)}
    _renamed(finding)
    check.summary = f"{(check.summary or '').strip()} {sentence}".strip()


def _without_aliases(check: Any, pattern: re.Pattern, noun: str, aliases: dict[str, str], left_out: str) -> None:
    """A shared title or description group loses a page's second address; a group left with one page is said under
    IDX-8's pair."""
    finding = next((f for f in check.findings if pattern.search(f.title)), None)
    if finding is None:
        return
    groups = finding.evidence.get("groups") or []
    kept, gone, changed = [], 0, False
    for shared in groups:
        urls = [url for url in shared.get("urls") or [] if url not in aliases]
        if len(urls) == len(shared.get("urls") or []):
            kept.append(shared)
            continue
        changed = True
        if len(urls) > 1:
            kept.append({**shared, "urls": urls, **({"count": len(urls)} if "count" in shared else {})})
        else:
            gone += 1
    if not changed:
        return
    urls = [url for url in _urls(finding) if url not in aliases]
    if not kept:
        check.findings = [f for f in check.findings if f is not finding]
        _settle(check, left_out.format(n=gone))
        return
    match = pattern.search(finding.title)
    removed = sorted(set(_urls(finding)) & set(aliases))
    finding.title = f"{len(kept)} {noun} are shared by {len(urls)} different indexable pages{finding.title[match.end():]}"
    finding.scope = scope_for(urls)
    finding.evidence = {**finding.evidence, "groups": kept,
                        **({"groups_total": len(kept)} if "groups_total" in finding.evidence else {}),
                        "second_addresses_left_out": removed}
    _renamed(finding)
    if gone:
        check.summary = f"{(check.summary or '').strip()} {left_out.format(n=gone)}".strip()


def _said_elsewhere(by_id: dict[str, Any]) -> None:
    """Take IDX-5's drafts and IDX-8's second addresses out of STR-1, STR-3, STR-15 and STR-16 (once per check object)."""
    drafts, aliases = _drafts_and_aliases(by_id)
    if not drafts and not aliases:
        return
    for check_id in ("STR-1", "STR-3", "STR-15", "STR-16"):
        check = by_id.get(check_id)
        if check is None or (check.evidence or {}).get(SAID):
            continue
        if check_id == "STR-15":
            _without_drafts(check, drafts, THIN, STR15_DRAFTS_LEFT_OUT)
        elif check_id == "STR-3":  # P2: a draft's questions are said with the draft
            _without_drafts(check, drafts, QA_BLOCK, STR3_DRAFTS_LEFT_OUT)
        elif check_id == "STR-1":
            _without_drafts(check, drafts, NO_TITLE, STR1_DRAFTS_LEFT_OUT)
            _without_aliases(check, STR1_TITLE, "title(s)", aliases, STR1_ALIASES_LEFT_OUT)
        else:
            _without_aliases(check, STR16_TITLE, "meta description(s)", aliases, STR16_ALIASES_LEFT_OUT)
        check.evidence = {**(check.evidence or {}), SAID: {"drafts": len(drafts), "second_addresses": len(aliases)}}


# -- copies and near-copies ----------------------------------------------------------------------------------------------

def _groups_of(check: Any) -> tuple[list[dict[str, Any]], list[Finding]]:
    """IDX-8's groups ({"urls", "signals", "same_text_pages", "variant_like", "pairs"}) and the findings they came from.
    An identical group whose pages all sit in one near-identical group is said on that group's line."""
    merged = next((f for f in check.findings if "duplicate_groups" in (f.evidence or {})), None)
    if merged is not None:
        return merged.evidence["duplicate_groups"], [merged]
    sources = [f for f in check.findings if EXACT_TITLE.search(f.title) or NEAR_TITLE.search(f.title)]
    near = [{"urls": sorted(_urls(f)), "signals": ["nearly_same"], "same_text_pages": 0,
             "variant_like": bool(f.evidence.get("variant_like")), "pairs": (f.evidence.get("pairs") or [])[:10]}
            for f in sources if NEAR_TITLE.search(f.title)]
    groups = list(near)
    for finding in sources:
        if not EXACT_TITLE.search(finding.title):
            continue
        urls = sorted(_urls(finding))
        home = next((g for g in near if set(urls) <= set(g["urls"])), None)
        if home is not None and set(urls) != set(home["urls"]):
            home["same_text_pages"] = max(home["same_text_pages"], len(urls))
        elif home is not None:
            home["signals"] = ["same_text", *home["signals"]]
        else:
            groups.append({"urls": urls, "signals": ["same_text"], "same_text_pages": 0, "variant_like": False, "pairs": []})
    return groups, sources


def _absorb(check: Any, pattern: re.Pattern, signal: str, groups: list[dict[str, Any]], left_out: str) -> bool:
    """Move the groups of a shared title or description whose pages all sit inside one duplicate group onto that group's
    line. True when anything moved."""
    finding = next((f for f in check.findings if pattern.search(f.title)), None)
    if finding is None:
        return False
    kept, moved_urls, moved = [], set(), 0
    for shared in finding.evidence.get("groups") or []:
        urls = set(shared.get("urls") or [])
        home = next((g for g in groups if len(urls) > 1 and urls <= set(g["urls"])), None)
        if home is None:
            kept.append(shared)
            continue
        if signal not in home["signals"]:
            home["signals"].append(signal)
        moved += 1
        moved_urls |= urls
    if not moved:
        return False
    match = pattern.search(finding.title)
    total = int(match["n"]) if match else len(finding.evidence.get("groups") or [])
    left = total - moved
    if left <= 0:
        check.findings = [f for f in check.findings if f is not finding]
        _settle(check, left_out.format(n=moved))
        return True
    urls = [url for url in _urls(finding) if url not in moved_urls]
    noun = "title(s)" if signal == "same_title" else "meta description(s)"
    rest = finding.title[match.end():] if match else ""
    finding.title = f"{left} {noun} are shared by {len(urls)} different indexable pages{rest}"
    finding.scope = scope_for(urls)
    finding.evidence = {**finding.evidence, "groups": kept,
                        **({"groups_total": left} if "groups_total" in finding.evidence else {}),
                        "said_under_idx8": moved}
    _renamed(finding)
    check.summary = f"{(check.summary or '').strip()} {left_out.format(n=moved)}".strip()
    return True


def _duplicates(by_id: dict[str, Any]) -> None:
    idx8 = by_id.get("IDX-8")
    if idx8 is None:
        return
    groups, sources = _groups_of(idx8)
    if not groups:
        return
    moved = False
    if "STR-1" in by_id:
        moved |= _absorb(by_id["STR-1"], STR1_TITLE, "same_title", groups, STR1_LEFT_OUT)
    if "STR-16" in by_id:
        moved |= _absorb(by_id["STR-16"], STR16_TITLE, "same_description", groups, STR16_LEFT_OUT)
    already = len(sources) == 1 and "duplicate_groups" in (sources[0].evidence or {})
    if already:
        sources[0].evidence["duplicate_groups"] = groups
        return
    if len(sources) < 2 and not moved:
        return
    from . import launch_gate

    urls = list(dict.fromkeys(url for g in groups for url in g["urls"]))
    gated: list[str] = []
    for finding in sources:
        for item in [*finding.launch_gated, *launch_gate.items_of("IDX-8", finding)[0]]:
            if item not in gated:
                gated.append(item)
    any_near = any("nearly_same" in g["signals"] for g in groups)
    evidence = {key: value for f in sources for key, value in f.evidence.items() if key in ("threshold", "method", "compared", "source")}
    merged = idx8_merged(groups, urls, near=any_near, variant=any(g["variant_like"] for g in groups),
                         evidence={**evidence, "merged_from": [f.title for f in sources]}, launch_gated=gated,
                         importance_tier=min(f.importance_tier for f in sources) if sources else 2)
    idx8.findings = [merged, *(f for f in idx8.findings if f not in sources)]


# -- a <head> that a body element ended early (DECISIONS 278) ------------------------------------------------------------
# TSEO-1 says that the tags after the break are not read (DECISIONS 260). STR-10 ("no og:title", "no meta description")
# and ACC-3 ("a robots tag outside <head>") read the same pages and said the same tags again, as missing or misplaced:
# 104 pages counted twice on one site, with a fix ("add og:title") that would not work while the widget stays. Those
# pages are said once, under TSEO-1, which names what it took in (`evidence.absorbed_from`).
HEAD_CLOSED = re.compile(r"end <head> early")
STR10_ABSENT = re.compile(r"^\d+ page\(s\) have no (og:[\w:]+|meta description)$")
ACC3_STRAY = re.compile(r"^\d+ page\(s\) carry a robots tag outside <head>(?P<rest>.*)$")
ROBOTS_NAMES = frozenset({"robots", "googlebot", "bingbot"})
HEAD_SAID = "head_closed_early"
HEAD_SAID_ELSEWHERE = ("Pages whose tag comes after a body element that ended <head> early are said under TSEO-1, not "
                       "here.")
HEAD_SAID_HERE = ("Tags these pages carry after the break are said here, not again as missing or misplaced elsewhere "
                  "(evidence.absorbed_from).")


def _after_break(result: Any) -> dict[str, set[str]]:
    """{url: the tag names that came after the element that ended its <head>} for every such page the crawl read."""
    out: dict[str, set[str]] = {}
    for page in getattr(result, "pages", None) or []:
        tags = ((getattr(page, "analysis", None) or {}).get("outside_head") or {})
        if tags.get("closed_early_by"):
            names = set(tags.get("properties") or []) | set(tags.get("meta") or [])
            if tags.get("canonical"):
                names.add("canonical")
            out[page.url] = names
    return out


def _head_closed(by_id: dict[str, Any], result: Any) -> None:
    tseo = by_id.get("TSEO-1")
    heads = [f for f in (tseo.findings if tseo else []) if HEAD_CLOSED.search(f.title)]
    if not heads or (tseo.evidence or {}).get(HEAD_SAID):
        return
    after = _after_break(result)
    absorbed = []
    for check_id in ("STR-10", "ACC-3"):
        check = by_id.get(check_id)
        if check is None:
            continue
        for finding in list(check.findings):
            if check_id == "STR-10" and (m := STR10_ABSENT.search(finding.title)):
                element = "description" if m.group(1) == "meta description" else m.group(1)
                moved = [u for u in _urls(finding) if element in after.get(u, ())]
                retitle = lambda n, m=m: f"{n} page(s) have no {m.group(1)}"
            elif check_id == "ACC-3" and (m := ACC3_STRAY.search(finding.title)):
                element = "robots"
                moved = [u for u in _urls(finding) if after.get(u, set()) & ROBOTS_NAMES]
                retitle = lambda n, m=m: f"{n} page(s) carry a robots tag outside <head>{m.group('rest')}"
            else:
                continue
            if not moved:
                continue
            absorbed.append({"check_id": check_id, "title_was": finding.title, "element": element, "pages": len(moved),
                             "urls": moved[:40]})
            kept = [u for u in _urls(finding) if u not in set(moved)]
            if not kept:
                check.findings.remove(finding)
                _settle(check, HEAD_SAID_ELSEWHERE)
                continue
            finding.title, finding.scope = retitle(len(kept)), scope_for(kept)
            finding.notes = [*finding.notes, HEAD_SAID_ELSEWHERE]
            _renamed(finding)
    for head in heads:
        mine = set(_urls(head))
        rows = [{**row, "pages": len(set(row["urls"]) & mine)} for row in absorbed if set(row["urls"]) & mine]
        if rows:
            head.evidence["absorbed_from"] = [{k: v for k, v in row.items() if k != "urls"} for row in rows]
            head.notes = [*head.notes, HEAD_SAID_HERE]
        cause = next((r.get("closed_by") for r in head.evidence.get("pages") or [] if r.get("closed_by")), None) or {}
        head.dedup_key = f"head_closed_early:{cause.get('tag') or '?'}#{cause.get('id') or ''}"
    tseo.evidence = {**(tseo.evidence or {}), HEAD_SAID: {"absorbed": len(absorbed)}}
