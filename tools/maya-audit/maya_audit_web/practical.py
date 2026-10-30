"""The practical report: the same findings, arranged for someone who has to act on them.

Nothing here judges a page. Every figure is counted from the report, the saved page evidence or the data panels;
the fix examples are fixed text chosen by the wording of a finding's title, and say so. The printable report
(`pdf.render_html`) and `GET /audits/{id}/summary` both read these structures, so they agree.

- `executive`: top problems, top opportunities, the first five actions
- `scorecard`: checks, problems by severity, notes and gaps, per area
- `timeline`: this week, this month, later
- `by_page`: the engine's problems by page (report `problem_summary`): what is wrong on each page, in the reader's
  language; "Whole site" first, with each site-wide problem's own title
- `page_table`: every page read, with its status, title, H1, words, schema types and number of issues
- `passed`: what was checked and found in order
- `sources`: every source of data in the report, with its date
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from maya_audit.report import (LANGUAGE_VALUES, WHOLE_OR_SECTION, detail_lines, merge_repeated, merged_pages, page_form, problem_summary,
                               whole_row_label)

from urllib.parse import urlsplit

from .strings import DEFAULT_LANGUAGE, current_language, has, language_name, t
from .wording import first_sentence, label, line, term
from .action_priority import performance_rows, ordered

TOP = 5
SERIOUS = ("S1", "S2", "S3")
SEVERITIES = ("S1", "S2", "S3", "S4")
# A short example of the fix, chosen by the finding's own title. First match wins; no match, no example.
EXAMPLES: tuple[tuple[str, str], ...] = (
    (r"no <title>|generic title", 'Use a concise title describing this page using its actual subject and approved brand name.'),
    (r"begin with the same", 'Put the actual page subject before repeated branding.'),
    (r"title\(s\) are shared|share the title", 'Describe each page distinctly using the content actually present.'),
    (r"title.*guidance band|page title\(s\) (above|below)", 'Review whether the title clearly describes the page. Character bands are editorial guidance, not Google limits.'),
    (r"meta description\(s\) (above|below)|have no meta description", 'Summarize what this page actually offers. Google has no fixed description length limit; display width varies.'),
    (r"meta description\(s\) are shared", "Write one description per page; do not repeat the homepage's on every page."),
    (r"homepage title does not name the brand", "<title>Brand: what the company does, in a few words</title>"),
    (r"no <h1>", "<h1>The page's subject, in the words a visitor would use</h1>"),
    (r"more than one <h1>", "Keep one <h1> for the page's subject; make the others <h2>."),
    (r"no subheadings", "Use headings that describe the actual sections; tables and lists may already provide useful structure."),
    (r"missing or empty alt|with no alt text|no alt attribute", 'Describe what the actual image communicates in context; use empty alt for a purely decorative image.'),
    (r"placeholder or template text", "Replace the leftover text (“Lorem ipsum”, “[Your Company Name]”) with the real wording, or unpublish the page."),
    (r"fewer than \d+ words", "Review the page purpose and add only information that visitors need and the evidence supports."),
    (r"no Organization structured data", '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Brand","url":"https://brand.example/","logo":"https://brand.example/logo.png"}</script>'),
    (r"JSON-LD that does not parse", "Paste the block into Google's Rich Results Test and fix the comma or quote it reports."),
    (r"missing Google-required properties", 'Check eligibility for the named structured-data feature. Add only properties supported by the visible page; never invent a price.'),
    (r"job opening\(s\) on the page itself", 'Describe each genuine open position with its verified details and actual publication date.'),
    (r"JobPosting", 'Use verified details of a real open position; do not copy sample dates or employers.'),
    (r"structured-data .* differs|not shown on the page|price\(s\) the page did not show", "Make the markup and the visible page say the same thing: one price, one currency, generated from the same data."),
    (r"canonical", '<link rel="canonical" href="https://brand.example/the-one-true-address">   (one per page, pointing to a page that works)'),
    (r"redirect chain|redirect loop", 'Compare the recorded request paths and client contexts before choosing a redirect remedy.'),
    (r"No HTTP to HTTPS redirect", "Redirect every http:// address to its https:// twin with a 301."),
    (r"soft 404|client error \(4xx\)|Link target returns", "Fix the link to the right address, or restore the page; a page that is gone should answer 404 or 410, not 200."),
    (r"server error \(5xx\)", "Find the error in the server log for the address listed and fix its cause; then request it again."),
    (r"listed only in the sitemap|clicks from the homepage", 'Link to the actual destination from a relevant page, using its verified topic as the anchor.'),
    (r"No usable XML sitemap|sitemap URLs .* are non-200", "Publish /sitemap.xml listing only live, canonical pages, and name it in robots.txt:  Sitemap: https://brand.example/sitemap.xml"),
    (r"robots\.txt returns an HTML page|robots\.txt returned a server error", "Serve a plain-text file at /robots.txt:\nUser-agent: *\nAllow: /\nSitemap: https://brand.example/sitemap.xml"),
    (r"noindex|nosnippet|no-snippet", 'Remove the instruction from pages that should be found:  <meta name="robots" content="index, follow">'),
    (r"no text at all|only with g", 'Use the actual destination topic as link text when the purpose is unclear from its accessible name and context.'),
    (r"no link to any other page", "Add the site's menu or footer to the page, or at least a link back to the section it belongs to."),
    (r"No .* page was found among", "Publish the missing pages (About, what you offer, Contact, common questions) and link them from the menu."),
    (r"missing from the raw HTML|appear only after Java|may be client-rendered", "Render the main text on the server (or pre-render it), so it is in the HTML before any script runs."),
    (r"html lang|another language than they declare", '<html lang="tr">   (the language the page is actually written in)'),
    (r"hreflang", '<link rel="alternate" hreflang="en" href="https://brand.example/en/"> on the Turkish page, and the matching link back on the English one.'),
    (r"og:image|have no og:|have no twitter:", 'Use the actual page title, summary and an existing accessible share-image URL; verify the image response before publishing.'),
    (r"no <main> or <article>|of their text in the main content", 'Inspect the existing content region. Low content ratio does not mean main is absent; add markup only if actually missing.'),
    (r"take more than .* s \(median\)", "Look at the slowest step for the addresses listed (server response, large images, blocking scripts) and fix that one first."),
    (r"blocks or challenges automated visitors", 'Compare the saved request with server logs. Identify the cause and intended access policy before changing security settings.'),
    (r"video or animation", "Put the message in text on the page as well: a heading and a paragraph beside the video, and a transcript."),
    (r"table-like <div>|<div> grids", 'Use a semantic table for genuinely tabular information; populate it only with verified page data.'),
)


def example_for(title: str) -> str | None:
    """A short example of the fix for a finding with this title, or None when there is no honest generic one."""
    example = next((example for pattern, example in EXAMPLES if re.search(pattern, title, re.IGNORECASE)), None)
    if example is None:
        return None
    # The words around the code are in the reader's language (locales/findings/<language>.json, "examples"); an example
    # that is only code has no entry and is shown as it is.
    from . import wording
    return ((wording.TABLES.get(current_language()) or {}).get("examples") or {}).get(example, example)


def shown(row: dict[str, Any], field: str = "title") -> str:
    """A finding row's title (or fix) as a person reads it: `title_shown`, or the engine's own for a row built without one."""
    return row.get(f"{field}_shown") or row.get(field) or ""


def merged(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows sharing semantic evidence identity and fully listed affected scope as one row,
    naming up to three pages then "and N more" (DECISIONS 225; engine `report.merge_repeated`). The first row keeps its
    place; `merged_ids` lists every finding the row stands for. Nothing is counted again: a headline keeps its own count."""
    out = []
    for same in merge_repeated(rows, lambda row: row.get("semantic_group") if row.get("semantic_group") and len(row.get("sample_pages") or []) >= int(row.get("pages_total") or 0) else ("individual", row["id"])):
        if len(same) == 1:
            out.append(same[0])
            continue
        named, more = merged_pages([(list(row.get("sample_pages") or []), int(row.get("pages_total") or 0)) for row in same])
        paths = ", ".join(_page_path(url) for url in named)
        title = (t("practical.merged.more", title=shown(same[0]), paths=paths, more=more) if more
                 else t("practical.merged", title=shown(same[0]), paths=paths))
        pages = list(dict.fromkeys(url for row in same for url in row.get('sample_pages') or []))
        scopes = [set(row.get('sample_pages') or []) for row in same]
        disjoint = sum(map(len, scopes)) == len(pages)
        counts = dict(same[0].get('counting') or {})
        details = list(same[0].get('details') or [])
        if counts:
            from .summary import count_line
            details = []
            for row in same:
                prior = count_line({}, counts=row['counting'])
                details.extend(f'[{row["id"]}] {line}' for line in row.get('details') or [] if line != prior)
            counts.update(affected_pages=len(pages), listed_unique_pages=len(pages))
            for field in ('occurrences', 'source_target_groups'):
                values = [(row.get('counting') or {}).get(field) for row in same]
                counts[field] = sum(values) if disjoint and all(isinstance(v, int) for v in values) else None
            values = [(row.get('counting') or {}).get('occurrences_per_template') for row in same]
            counts['occurrences_per_template'] = values[0] if all(v == values[0] for v in values) else None
            details.append(count_line({}, counts=counts))
        out.append({**same[0], "title_shown": title, "what": title, "merged_ids": [row["id"] for row in same],
                    "sample_pages": pages[:5], "pages_total": len(pages),
                    "affects": t('result.affects.pages', count=len(pages)), "counting": counts, "details": details,
                    "member_counts": {row['id']: row.get('counting') for row in same}})
    return out


def issue(row: dict[str, Any]) -> dict[str, Any]:
    """One finding as what / where / why / fix (with an example) / owner / effort. `what` and `fix` are in the reader's
    language; the example is chosen by the engine's own title and stays code."""
    return {"id": row["id"], "check_id": row["check_id"], "severity": row["severity"], "severity_label": row["severity_label"],
            "area": row["area"], "what": shown(row), "where": row["affects"], "pages": row["sample_pages"], "pages_total": row["pages_total"],
            "why": row["why"], "fix": shown(row, "fix"), "example": None if row.get("judgment",{}).get("qualified") else example_for(row["title"]), "owner": row["estimates"]["owner_label"],
            "effort": row["estimates"]["effort_label"], "source": row.get("source"), "confidence": row["confidence_label"],
            "details": row.get("details") or [], "unverified": row.get("unverified"), "judgment": row.get("judgment"), "verification": row.get("verification"),
            "link_cards": row.get("link_cards")}


def when(row: dict[str, Any]) -> str:
    """Which part of the timeline a finding belongs to: the harm first, then how small the job is. A finding from a
    rule not yet validated on real sites, or one the evidence only estimates or infers, is confirmed before it is
    scheduled: "Verify first", never "This week" (CR-34). A measured performance diagnostic keeps its own place."""
    severity, effort = row["severity"], row["estimates"]["effort"]
    if not row.get("action_kind") and (row.get("unverified") or row.get("confidence") in ("estimated", "inferred")):
        return "verify"
    if severity in ("S1", "S2") or (severity == "S3" and (effort == "S" or row.get("action_kind"))):
        return "week"
    if severity == "S3" or (severity == "S4" and effort == "S"):
        return "month"
    return "later"


def timeline(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """This week, this month, later; and "Verify first" only when something is waiting to be confirmed."""
    problems = merged([row for row in rows if row["requires_fix"]])
    steps = [{"id": name, "label": t(f"practical.when.{name}"), "note": t(f"practical.when.{name}.note"),
              "items": [issue(row) for row in problems if when(row) == name]} for name in ("week", "verify", "month", "later")]
    return [step for step in steps if step["id"] != "verify" or step["items"]]


def also_line(rows: list[dict[str, Any]], row: dict[str, Any], named: int = 2) -> str | None:
    """The other S1-S3 problems of `row`'s check, said after the row (count and the first two titles): a short list is one
    row per check, and must not hide a second Medium-or-worse problem of that check (G25)."""
    if row["severity"] not in SERIOUS:
        return None
    others = [shown(r) for r in rows if r is not row and r["check_id"] == row["check_id"] and r["severity"] in SERIOUS]
    if not others:
        return None
    titles = "; ".join(others[:named])
    return t("pdf.exec.also_more", titles=titles, count=len(others) - named) if len(others) > named else t("pdf.exec.also", titles=titles)


def one_per_check(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The first row of each check, in the order given: a short list names distinct problems, not one check five times."""
    seen: set[str] = set()
    return [row for row in rows if not (row["check_id"] in seen or seen.add(row["check_id"]))]


def scorecard(areas: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Counts per area. Not a score: a count of what was checked and what was found."""
    out = []
    for area in areas:
        mine = [row for row in rows if row["area"] == area["area"]]
        checks = area["checks"]
        out.append({"area": area["area"], "label": area["label"], "checks": len(checks),
                    "in_order": sum(1 for check in checks if check["status"] == "pass"),
                    "by_severity": {level: sum(1 for row in mine if row["severity"] == level) for level in SEVERITIES},
                    "problems": sum(1 for row in mine if row["requires_fix"]), "notes": sum(1 for row in mine if not row["requires_fix"]),
                    "not_checked": area["not_checked"], "partial": area.get("partial", 0)})
    return out


def passed(areas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What else was checked and found in order, by area. Beside the checks that passed stand the ones that found
    nothing on the pages read and are partial only because pages were found and not read (`read_only`, DECISIONS 189):
    each says "No problem found on the 50 pages read (9 not read)" in front of its own summary. They are not counted
    as in order (`scorecard`: partial is never a pass) and stay listed under what could not be checked."""
    def shown(c: dict[str, Any]) -> dict[str, Any]:
        row = {"check_id": c["check_id"], "title": c["title"], "title_shown": c.get("title_shown") or c["title"], "summary": c["summary"],
               "summary_shown": c.get("summary_shown") or c["summary"]}
        if c.get("read_only"):
            row.update(read_only=True, read_only_shown=c["read_only_shown"], summary=f'{c["read_only_english"]}. {row["summary"]}',
                       summary_shown=f'{c["read_only_shown"]}. {row["summary_shown"]}')
        return row

    def listed(c: dict[str, Any]) -> bool:
        return c["status"] == "pass" or bool(c.get("read_only"))

    return [{"area": area["area"], "label": area["label"], "checks": [shown(c) for c in area["checks"] if listed(c)]}
            for area in areas if any(listed(c) for c in area["checks"])]


def _data(backlinks: dict[str, Any] | None, check_id: str) -> dict[str, Any]:
    check = next((c for c in (backlinks or {}).get("checks") or [] if c["check_id"] == check_id and c["status"] != "not_assessed"), None)
    return (check or {}).get("data") or {}


def opportunities(backlinks: dict[str, Any] | None, speed: dict[str, Any] | None, rows: list[dict[str, Any]]) -> list[str]:
    """What could be gained, from the data panels where they ran, and otherwise from the smallest fixes."""
    out = []
    from maya_audit.dataforseo.insights import qualified_opportunity_data
    wins = qualified_opportunity_data(_data(backlinks, "DFS-5"))
    table = [row for row in (wins.get("table") or {}).get("rows") or [] if (len(row) < 5 or row[-1] in ("branded", "relevant")) and (wins.get('opportunity_evidence') or {}).get(row[0], True)]
    if table:
        out.append(t("practical.opp.quick_wins", count=len(table),
                     examples="; ".join(t("practical.opp.quick_wins.example", keyword=row[0], searches=row[1], position=row[2]) for row in table[:3] if isinstance(row[1], int))))
    editorial = (wins.get('editorial_opportunities') or {}).get('rows') or []
    if editorial:
        out.append(t('practical.opp.editorial', count=len(editorial), examples='; '.join(str(r[0]) for r in editorial[:3])))
    for check_id, key in (("DFS-7", "practical.opp.ai.google"), ("DFS-8", "practical.opp.ai.chatgpt")):
        seen = _data(backlinks, check_id)
        # Only a measured zero is said: an empty or unreadable provider sample is not evidence about the site.
        if seen and not seen.get("mentioned") and seen.get("sample", "measured_zero") == "measured_zero":
            out.append(t(key))
    lab = _data(backlinks, "DFS-9")
    if lab.get("past_good_threshold"):
        out.append(t("practical.opp.lab", metrics=", ".join((term(name) or name)+": "+str(value) for name,value in (lab.get("metrics") or {}).items() if name != "Performance score (0–100)" and value is not None), score=(lab.get("metrics") or {}).get("Performance score (0–100)")))
    if speed and speed.get("status") == "assessed" and not speed.get("passes_core_web_vitals"):
        out.append(_field_speed(speed))
    profile = _data(backlinks, "DFS-12")
    if profile.get("found") and profile.get("missing"):
        out.append(t("practical.opp.profile", missing=", ".join(term(name) or name for name in profile["missing"])))
    rivals = ((_data(backlinks, "DFS-6").get("table") or {}).get("rows") or [])
    if rivals:
        out.append(t("practical.opp.rivals", names=", ".join(str(row[0]) for row in rivals[:3])))
    small = [row for row in rows if row["requires_fix"] and row["estimates"]["effort"] == "S" and row["severity"] in ("S3", "S4")]
    if small and len(out) < TOP:
        out.append(t("practical.opp.small", count=len(small), examples="; ".join(shown(row) for row in small[:2])))
    return out[:TOP]


def _field_speed(speed: dict[str, Any]) -> str:
    """Real visitors' Core Web Vitals that are not good. English: the report's own sentence. Another language: the same
    figures from the report's `crux.metrics` (the metric's name and value stay as they are, the rating is translated)."""
    if current_language() == DEFAULT_LANGUAGE:
        return t("practical.opp.cwv", summary=speed["summary"])
    worst = [f"{row['label']} {row['shown']} ({t('crux.rating.' + row['rating'])})" for row in speed.get("metrics") or []
             if row.get("rating") and row["rating"] != "good"]
    return t("practical.opp.cwv.worst", worst="; ".join(worst)) if worst else t("practical.opp.cwv.partial")


def top_title(shown: int, total: int, key: str = "pdf.exec.problems") -> str:
    """"Top 5 of 15 problems", or "All 3 problems" when every one is shown. With none shown, the plain heading."""
    if not shown or not total:
        return t("pdf.exec.problems.plain")
    if total == 1:
        return t("pdf.exec.problems.one")
    return t("pdf.exec.problems.all", total=total) if total <= shown else t(key, shown=shown, total=total)


# The words an instruction starts with. An action in "First five actions" begins with one of them: it says what to do,
# not why (Owner, 2026-10-12). The list is every verb the engine's own fix texts open a sentence or a clause with.
ACTION_VERBS = frozenset("""add allow ask audit break change check choose code combine compare configure confirm consolidate corroborate correct decide
declare define describe drop ensure expand fill find fix generate give improve include inspect investigate keep let limit link list look lower
make mark merge move name open paste percent-encode pick point provide publish put read reduce redirect regenerate reissue remove render renew replace reproduce resolve
restore recover return review say send serve server-render set shorten show shrink split start stop switch take test translate trim turn update use
verify wrap write""".split())
_SENTENCES = re.compile(r"(?<=[.!?])\s+")
_LEAD_IN = re.compile(r"^(?P<lead>If [^,;]+|For each [^,;]+|To [^,;]+|Optional, for [^,;:]+)[,:] (?P<rest>.+)$", re.DOTALL)
# Turkish puts the verb last: an instruction ends in the polite imperative (-ın, -in, -un, -ün, -ınız…).
_TR_IMPERATIVE = re.compile(r"(?:[ıiuü]n|[ıiuü]n[ıiuü]z)$")


def _first_word(text: str) -> str:
    found = re.match(r"[^\w<]*([\w-]+)", text or "")
    return found.group(1).lower() if found else ""


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def action_sentence(fix: str, language: str | None = None) -> str:
    """The sentence of a fix that says what to do, starting with the verb. A fix that opens with the reason ("Engines
    that honor the canonical will index the target…") gives its instruction ("Make the page self-canonical…"); a
    condition in front is moved behind ("If these pages should appear…, remove the directive." becomes "Remove the
    directive if these pages should appear…"). When no sentence is an instruction, the first sentence is kept."""
    language = language or current_language()
    sentences = [part.strip() for part in _SENTENCES.split((fix or "").strip()) if part.strip()]
    if not sentences:
        return ""
    if language == "tr":
        for sentence in sentences:
            clauses = [clause.strip() for clause in sentence.rstrip(".!").split(";")]
            for clause in clauses:
                last = re.sub(r"\s*\([^()]*\)\s*$", "", clause).split()[-1:] or [""]
                if _TR_IMPERATIVE.search(last[0].strip("“”\"'.,:").lower()):
                    return (_capital(clause) + ".")[:300] if len(clauses) > 1 else sentence[:300]
        return sentences[0][:300]
    for sentence in sentences:
        if _first_word(sentence) in ACTION_VERBS:
            return sentence[:300]
    for sentence in sentences:
        led = _LEAD_IN.match(sentence)
        if led and _first_word(led["rest"]) in ACTION_VERBS:
            rest, lead = led["rest"].rstrip(".!"), led["lead"]
            lead = lead[:1].lower() + lead[1:]
            return (f"{_capital(rest)} {lead}." if lead.startswith("if ") else f"{_capital(rest)} ({lead}).")[:300]
        for clause in sentence.rstrip(".!").split(";")[1:]:  # "That is usually harmless; serve plain text if …"
            if _first_word(clause) in ACTION_VERBS:
                return (_capital(clause.strip()) + ".")[:300]
    return sentences[0][:300]


def _page_path(url: str) -> str:
    parts = urlsplit(url)
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def specific_action(row: dict[str, Any]) -> str | None:
    """An action that names the page, for a problem whose fix is the same sentence on every site and clearer with the
    address in it. Today: a canonical that points at another page's content."""
    if row["check_id"] == "IDX-4" and "canonicalized to a URL with different content" in (row.get("title") or ""):
        pages = row.get("sample_pages") or []
        total = row.get("pages_total") or len(pages)
        if total == 1 and pages:
            return t("practical.action.canonical_self.one", path=_page_path(pages[0]))
        if total > 1:
            return t("practical.action.canonical_self.many", count=total)
    return None


def first_actions(problems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The first five different things to do. Problems are walked in priority order; two from the same check with the
    same fix are one action, said once, naming both. So the list holds five distinct actions (or as many as there are),
    not the same sentence twice."""
    actions: dict[tuple[str, str], dict[str, Any]] = {}
    for row in ordered(problems):
        text = (shown(row, "fix") if row.get("action_kind") or (row.get("judgment") or {}).get("qualified") else
                specific_action(row) or action_sentence(shown(row, "fix")) or shown(row))
        key = (row["check_id"], text)
        if key in actions:
            actions[key]["titles"].append(shown(row))
        elif len(actions) < TOP:
            actions[key] = {"text": text, "titles": [shown(row)], "owner": row["estimates"]["owner_label"],
                            "effort": row["estimates"]["effort_label"], "when": t(f"practical.when.{when(row)}")}
    return [{"text": a["text"], "for": "; ".join(a["titles"]), "titles": a["titles"], "owner": a["owner"], "effort": a["effort"],
             "when": a["when"]} for a in actions.values()]


def executive(rows: list[dict[str, Any]], backlinks: dict[str, Any] | None, speed: dict[str, Any] | None, *, withheld: str | None) -> dict[str, Any]:
    """One page: the worst problems, the best opportunities, the first five things to do."""
    problems = [row for row in rows if row["requires_fix"]]
    # The same order as the first actions (harm, then evidence quality: an unverified rule or an estimate after a
    # verified finding of the same tier), and one row per check (CR-19).
    rows_in_order = ordered(merged(problems))
    top = [] if withheld else one_per_check(rows_in_order)[:TOP]
    return {"problems": [{"severity": row["severity"], "severity_label": row["severity_label"], "title": shown(row), "where": row["affects"],
                          "unverified": row.get("unverified"), "also": also_line(rows_in_order, row)} for row in top],
            "problems_total": len(problems), "withheld": withheld,
            "problems_title": top_title(len(top), len(problems)),
            # Said under a list that is not the whole of it: where every problem is.
            "more": t("pdf.exec.more", total=len(problems)) if top and len(problems) > len(top) else None,
            "opportunities": opportunities(backlinks, speed, rows),
            "actions": [] if withheld else first_actions(merged(problems) + performance_rows(backlinks, speed)),
            "no_problems": t("practical.none") if not problems else None}


_first_sentence = first_sentence


def _schema_types(blocks: list[str]) -> list[str]:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            kind = node.get("@type")
            for name in kind if isinstance(kind, list) else [kind]:
                if isinstance(name, str) and name not in found:
                    found.append(name)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for raw in blocks or []:
        try:
            walk(json.loads(raw))
        except (ValueError, TypeError):
            if "unreadable" not in found:
                found.append("unreadable")
    return found


def details(entry: dict[str, Any]) -> list[str]:
    """The values behind one finding or review item (engine `detail_lines`), in the reader's language: both sides of a
    price that differs or could not be told apart, the names a brand goes by. A line about one page starts with its
    path. Empty for a finding whose title already says everything."""
    out = []
    for line in detail_lines(entry):
        values = dict(line["values"])
        if line["kind"] == "brand_name":
            values["sources"] = ", ".join(t("detail.source", source=t(f"detail.source.{source['source']}") if has(f"detail.source.{source['source']}")
                                            else source["source"], pages=source["pages"]) for source in values["sources"])
        if values.get("why_code") and has(f"detail.why.{values['why_code']}"):
            values["why"] = t(f"detail.why.{values['why_code']}")
        if isinstance(values.get("signals"), list):
            values["signals"] = signals_shown(values)
        text = t(f"detail.{line['kind']}", **values)
        there = urlsplit(line["url"]) if line.get("url") else None
        path = ((there.path or "/") + (f"?{there.query}" if there.query else "")) if there else None
        out.append(f"{path}: {text}" if path else text)
    return out


def signals_shown(values: dict[str, Any]) -> str:
    """What the pages of one duplicate group share (IDX-8, DECISIONS 225), in the reader's language."""
    said = [t(f"detail.signal.{code}") for code in values.get("signals") or [] if has(f"detail.signal.{code}")]
    if values.get("same_text"):
        said.append(t("detail.signal.same_text_some", same_text=values["same_text"]))
    return ", ".join(said)


def names_line(entry: dict[str, Any]) -> str | None:
    """The names a brand goes by, in one line, to stand after the finding's title in the "Whole site" row."""
    lines = details({**entry, "evidence": {"variants": (entry.get("evidence") or {}).get("variants")}}) if entry.get("check_id") == "STR-5" else []
    return "; ".join(lines) or None


def page_line(item: dict[str, Any], titles: dict[str, str] | None = None) -> str:
    """What one problem is on one page (an engine `page_item`), in the reader's language. The engine chooses the kind
    and whether the page's own number is known; the words are this layer's (`bypage.<kind>`, `bypage.<kind>.plain`)."""
    # A language is named in the reader's language ("English", "İngilizce"); the report keeps its code ("en").
    values = {name: language_name(value) if name in LANGUAGE_VALUES else value for name, value in item["values"].items()}
    if isinstance(values.get("signals"), list):
        values["signals"] = signals_shown(values)
    if item["kind"] == "affected" and titles and item.get("finding_id") in titles:
        values["title"] = titles[item["finding_id"]]  # the title as this layer shows it everywhere else
    if page_form(item) == "plain":
        return t(f"bypage.{item['kind']}.plain", **values)
    return t(f"bypage.{item['kind']}", **values) + (t("bypage.more", more=values["more"]) if values.get("more") else "")


def by_page(summary: dict[str, Any] | None, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """"Problems by page": the engine's rows (report `problem_summary`) with the labels a table needs. "Whole site" is
    the first row and keeps each site-wide problem's own title. A page's row says, in `lines`, what each problem is on
    that page, with that page's own numbers (never the site-wide count from the title). None when there is no problem
    to list: no empty table is shown. Nothing is counted here."""
    if not summary:
        return None
    titles = {row["id"]: shown(row) for row in rows}  # as this layer shows them everywhere else
    # The "Whole site" row also says what a count stands for: the names behind "The brand is named 5 different ways".
    whole = {row["id"]: f"{shown(row)}: {row['names_line']}" for row in rows if row.get("names_line")}

    def line(entry: dict[str, Any], url: str | None) -> dict[str, Any]:
        shown = [(whole if url is None else {}).get(i) or titles.get(i, i) for i in entry["finding_ids"]]
        whole_label = (t("practical.by_page.site_level") if summary.get("single_page")
                       else t("practical.by_page.whole_or_section") if whole_row_label(summary) == WHOLE_OR_SECTION else t("practical.by_page.whole_site"))
        return {"whole_site": url is None, "url": url, "label": whole_label if url is None else url,
                "problems": entry["problems"], "worst_severity": entry["worst_severity"],
                "worst_severity_label": t(f"result.severity.{entry['worst_severity']}"),
                "finding_ids": list(entry["finding_ids"]), "titles": shown,
                # Two findings can say the same thing about a page: a line is shown once (the count keeps both).
                "lines": list(dict.fromkeys([page_line(item, titles) for item in entry["items"]] if url is not None and entry.get("items") else shown))}

    table = ([line(summary["whole_site"], None)] if summary["whole_site"]["problems"] else []) + [
        line(entry, entry["url"]) for entry in summary["by_page"]]
    not_listed = [{"finding_id": entry["finding_id"], "title": titles.get(entry["finding_id"], entry["finding_id"]), "pages": entry["pages"],
                   "line": t("practical.by_page.not_listed", title=titles.get(entry["finding_id"], entry["finding_id"]), count=entry["pages"])}
                  for entry in summary["not_listed"]]
    # Sitemaps, robots.txt and documents with a problem: files, not pages, listed under the table with each problem's title.
    files = [{**line(entry, entry["url"]), "lines": [titles.get(i, i) for i in entry["finding_ids"]]} for entry in summary.get("files") or []]
    if not table and not not_listed and not files:
        return None
    return {"title": t("practical.by_page.title"), "rows": table, "total": len(table), "not_listed": not_listed,
            "columns": [t("pdf.col.page"), t("practical.by_page.col.problems"), t("practical.by_page.col.worst"), t("practical.by_page.col.titles")],
            "files": {"title": t("practical.by_page.files.title"), "rows": files,
                      "columns": [t("practical.by_page.files.col"), t("practical.by_page.col.problems"), t("practical.by_page.col.worst"),
                                  t("practical.by_page.files.col.titles")]},
            "note": t("practical.by_page.note")}


def page_table(artifacts: Path, report: dict[str, Any], summary: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every page read, from the evidence saved with the audit: what Firecrawl read where it read, Maya's own otherwise.

    Words are counted in the page's main text as saved (cut at the evidence limit, which is then said). Issues are the
    engine's per-page counts (`summary`, the report's `problem_summary`): the problems that name the page. A problem
    that affects the whole site is not counted against each page. Without `summary`, the report's own is used, or the
    engine function is applied to the report and the full lists saved beside it."""
    if summary is None:
        summary = report.get("problem_summary")
    if not isinstance(summary, dict):
        try:
            affected = json.loads((artifacts / "affected-urls.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            affected = {}
        summary = problem_summary([f for check in report["checks"] for f in check["findings"]], affected or None,
                                  pages_checked=report["page_counts"]["pages_checked"])
    issues: dict[str, int] = {row["url"]: row["problems"] for row in summary["by_page"]}
    rows: dict[str, dict[str, Any]] = {}
    for folder, reader in (("evidence", "Maya"), ("evidence-firecrawl", "Firecrawl")):  # the reader's copy replaces Maya's
        for path in sorted((artifacts / folder).glob("[0-9]*.json")):
            try:
                page = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            url = page.get("url")
            if not url or (reader == "Maya" and not (page.get("title") or page.get("main_text"))):
                continue
            headings = page.get("headings") or []
            first = next((h.get("text") for h in headings if isinstance(h, dict) and h.get("level") == 1), None)
            rows[url] = {"url": url, "status": page.get("status"), "title": page.get("title"), "h1": first,
                         "h1_count": sum(1 for h in headings if isinstance(h, dict) and h.get("level") == 1),
                         "words": len((page.get("main_text") or "").split()), "words_cut": bool(page.get("main_text_truncated")),
                         "schema": _schema_types(page.get("json_ld_blocks") or []), "issues": issues.get(url, 0), "read_by": reader}
    # Pages Maya's crawler asked for and could not read (errors, redirects, blocks) still belong in the list.
    for page in report["crawl"].get("pages") or []:
        if page["url"] not in rows:
            rows[page["url"]] = {"url": page["url"], "status": page.get("status"), "title": None, "h1": None, "h1_count": 0, "words": None,
                                 "words_cut": False, "schema": [], "issues": issues.get(page["url"], 0), "read_by": None}
    ordered = sorted(rows.values(), key=lambda row: (-row["issues"], row["url"]))
    return {"rows": ordered, "total": len(ordered), "with_issues": sum(1 for row in ordered if row["issues"]),
            "note": t("practical.pages.note")}


def sources(report: dict[str, Any], backlinks: dict[str, Any] | None, speed: dict[str, Any] | None) -> list[dict[str, str]]:
    """Every source of data in the report, what it supplied, and its date."""
    crawl = report["crawl"]
    out = [{"source": t("practical.source.maya", agent=crawl.get("user_agent") or "Maya-Audit"), "what": t("practical.source.maya.what", requests=len(crawl.get("requests") or [])),
            "date": f"{(crawl.get('started_at') or '')[:16]} → {(crawl.get('finished_at') or '')[:16]} UTC"}]
    reader = report.get("firecrawl") or {}
    if reader:
        zdr = (reader.get("zero_data_retention") or {}).get("status")
        dates = sorted(str(call.get("data_from"))[:16] for call in reader.get("calls") or [] if call.get("data_from"))
        out.append({"source": t("practical.source.firecrawl", proxy=reader.get("proxy")),
                    "what": t("practical.source.firecrawl.what", pages=reader.get("pages_read") or 0, credits=(reader.get("credits") or {}).get("used_or_reserved", 0),
                                zdr=(term(zdr) or zdr) if zdr and current_language() != DEFAULT_LANGUAGE else zdr),
                    # The client's copy: what was read, without the operator's data-retention setting (H38).
                    "what_client": t("practical.source.firecrawl.what_client", pages=reader.get("pages_read") or 0),
                    "date": (f"{dates[0]} → {dates[-1]} UTC" if dates else "")})
    for check in (backlinks or {}).get("checks") or []:
        if check.get("data_from"):
            out.append({"source": "DataForSEO " + (check.get("endpoint") or ""), "what": check.get("title_shown") or check["title"],
                        "date": str(check["data_from"])[:16] + (" · " + t("result.data.cached") if check.get("from_cache") else "")})
    if speed and speed.get("status") == "assessed":
        out.append({"source": speed.get("source_shown") or speed["source"], "what": t("result.crux.title"), "date": t("practical.source.until", date=speed.get("data_until") or "?")})
    for source in (report.get("archives") or {}).get("sources") or []:
        dates = sorted(page["date"][:10] for page in source.get("pages") or [])
        out.append({"source": source["name"], "what": t("result.archives.pages", count=source["pages_read"]),
                    "date": f"{dates[0]} → {dates[-1]}" if dates else ""})
    owned = report.get("ownership")
    if owned:
        out.append({"source": t("verify.title"), "what": line(owned["summary"])[0], "date": (owned.get("checked_at") or "")[:16]})
    return out


def build(view: dict[str, Any], rows: list[dict[str, Any]], report: dict[str, Any], artifacts: Path | None) -> dict[str, Any]:
    """Everything the practical report adds, from one audit's view, its finding rows and its saved files."""
    backlinks, speed = view.get("backlinks"), view.get("crux")
    return {"executive": executive(rows, backlinks, speed, withheld=view.get("first_action_withheld")),
            "performance_diagnostics": [issue(row) for row in performance_rows(backlinks,speed)],
            "scorecard": scorecard(view["areas"], rows), "timeline": timeline(ordered(rows + performance_rows(backlinks, speed))),
            "issues": [issue(row) for row in rows if row["requires_fix"]],
            "by_page": by_page(view.get("problem_summary"), rows),
            "pages": page_table(artifacts, report, view.get("problem_summary")) if artifacts is not None else {"rows": [], "total": 0, "with_issues": 0, "note": ""},
            "passed": passed(view["areas"]), "sources": sources(report, backlinks, speed)}
