"""The team report's text library (DECISIONS 307): every client sentence the pro report needs, per rule id, per merge
group and per Note-card topic, in Turkish and English, and the page-1 sentences built from the top cards.

`texts/tr.json` and `texts/en.json` have the same structure:

- `rules[<rule id>]`: title (the card's action), finding (what is wrong, for the findings table and "Teyit edin"),
  explanation (one sentence: what to do), why (why it matters), steps (2-4), steps_by_platform (optional:
  {"Shopify": [...]}), verify (one sentence: where to look and what to see), summary (2-4 words, for page 1).
- `groups[<merge group id>]`: the same fields except title and finding, which stay in the engine's merge table
  (`maya_audit.client_selection.MERGE_GROUPS`) beside the group's rules.
- `notes[<topic>]`: one step and a summary for each topic a Note card can hold (schema, hygiene, content, page load,
  share); `_more` lists the rest when a card has more topics than steps.
- `page1`: the templates of the verdict, assessment, priorities, next step, caveat and month summary.
- `generic`: the last resort when a rule has no entry (a rule added later); a test keeps every rule covered.

The engine's own action catalogue (`maya_audit/rule_actions.json`, DECISIONS 270) wins for title, steps and platform
steps: those are the approved card steps, and their conditions are checked by the release gate. The library supplies
every other field and the title/steps of rules the catalogue does not have.

The texts hold no digits: every number in a report comes from report.json (the validator refuses any other). A
template's `{name}` is filled from the card; `[[ ... ]]` is an optional part, dropped when a name in it has no value.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANGS = ("tr", "en")
FIELDS = ("title", "finding", "explanation", "why", "steps", "verify", "summary")
LIMITS = {"title": 80, "finding": 70, "explanation": 150, "why": 170, "verify": 150, "summary": 40}
STEP_CHARS, STEP_LINES = 100, 4
_OPTIONAL = re.compile(r"\[\[(.*?)\]\]", re.S)
_NAME = re.compile(r"\{(\w+)\}")


@lru_cache(maxsize=None)
def library(lang: str) -> dict:
    return json.loads((HERE / "texts" / f"{lang}.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _catalogue() -> dict:
    return json.loads((HERE.parents[1] / "maya_audit" / "rule_actions.json").read_text(encoding="utf-8"))["actions"]


def _merge_groups() -> dict:
    from maya_audit.client_selection import MERGE_BY_RULE, MERGE_GROUPS
    return {"by_rule": MERGE_BY_RULE, "groups": {g["id"]: g for g in MERGE_GROUPS}}


def fill(template: str | None, **values) -> str | None:
    """`{name}` from values; an optional `[[...]]` part is dropped when a name in it has no value (None or "")."""
    if template is None:
        return None

    def optional(m):
        names = _NAME.findall(m.group(1))
        return m.group(1) if all(values.get(n) not in (None, "") for n in names) else ""

    text = _OPTIONAL.sub(optional, template)
    return _NAME.sub(lambda m: str(values.get(m.group(1), "")), text).strip()


_PLURAL = re.compile(r"\{(\w+):([^{}|]*)\|([^{}]*)\}")


def label(template: str, **values) -> str:
    """str.format for the labels (refs/etiketler.json) with `{name:singular|plural}` (DECISIONS 309): "{read:page|pages}"
    -> "1 page", "15,400 pages". A value may be a formatted number ("15.400"); the count is read from its digits."""
    def one(m):
        value = values.get(m.group(1))
        digits = re.search(r"\d[\d,.]*", str(value if value is not None else ""))
        n = int(re.sub(r"[,.]", "", digits.group(0))) if digits else None
        return f"{value} {m.group(2) if n == 1 else m.group(3)}"
    return _PLURAL.sub(one, template).format(**values)


def lower_first(text: str, lang: str) -> str:
    """'Sayfa HTML ağırlığı' -> 'sayfa HTML ağırlığı'; an acronym ('CDN önbelleği') or a tag stays as it is."""
    if not text or len(text) < 2 or not text[0].isupper() or text[1].isupper() or not text[1].isalpha():
        return text
    # A name with a capital inside its first word stays as written (DECISIONS 309): "JavaScript'e", "WordPress",
    # never "javaScript'e" after "ve" / "and".
    first_word = re.split(r"[\s'’\-/(]", text, maxsplit=1)[0]
    if any(c.isupper() for c in first_word[1:]):
        return text
    first = {"I": "ı", "İ": "i"}.get(text[0], text[0].lower()) if lang == "tr" else text[0].lower()
    return first + text[1:]


def upper_first(text: str, lang: str) -> str:
    if not text:
        return text
    first = {"i": "İ", "ı": "I"}.get(text[0], text[0].upper()) if lang == "tr" else text[0].upper()
    return first + text[1:]


def join(items: list[str], lang: str) -> str:
    p = library(lang)["page1"]
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return p["list_join"].join(items[:-1]) + p["list_last"] + items[-1]


def rule(rule_id: str | None, lang: str) -> dict:
    """The full entry of one rule: the library's fields with the catalogue's title, steps and platform steps on top;
    the generic entry for a rule with none (never empty)."""
    lib = library(lang)
    entry = dict(lib["generic"])
    entry.update((lib.get("rules") or {}).get(rule_id or "", {}))
    cat = _catalogue().get(rule_id or "") or {}
    if cat.get(lang):
        entry["title"] = cat[lang]
    approved = list((cat.get("steps") or {}).get(lang) or [])
    conditions = list(cat.get("step_when") or [])
    conditional = {line for n, line in enumerate(approved) if n < len(conditions) and conditions[n]}
    if len(approved) >= 2 and not conditional:
        entry["steps"] = approved
    # A catalogue step with a condition (step_when, DECISIONS 278) is shown only through the catalogue, where the
    # release gate checks it; the library never prints it unconditionally.
    entry["steps"] = [line for line in entry.get("steps") or [] if line not in conditional]
    if len(entry["steps"]) < 2:
        entry["steps"] = entry["steps"] + [line for line in lib["generic"]["steps"] if line not in entry["steps"]][:2 - len(entry["steps"])]
    for platform, by_lang in (cat.get("steps_by_platform") or {}).items():
        if (by_lang or {}).get(lang):
            entry.setdefault("steps_by_platform", {})
            entry["steps_by_platform"] = {**entry["steps_by_platform"], platform: list(by_lang[lang])}
    entry["rule_id"] = rule_id
    return entry


def group(group_id: str, lang: str) -> dict:
    """A merge group's entry: title, finding and fix from the engine's merge table, the rest from the library."""
    lib = library(lang)
    g = _merge_groups()["groups"][group_id]
    entry = dict(lib["generic"])
    entry.update((lib.get("groups") or {}).get(group_id, {}))
    entry["title"] = g["title"].get(lang) or g["title"]["en"]
    entry["finding"] = g["finding"].get(lang) or g["finding"]["en"]
    entry["group"] = group_id
    return entry


def for_finding(finding: dict, lang: str, merged: bool = True) -> dict:
    """The entry a card or a row of this finding uses: its merge group's when it has one, else its rule's."""
    rule_id = finding.get("rule_id")
    g = _merge_groups()["by_rule"].get(rule_id or "") if merged else None
    return group(g["id"], lang) if g else rule(rule_id, lang)


def steps(entry: dict, platform: str | None = None) -> tuple[list[str], str | None]:
    """(steps, platform) — the platform's own steps when the site runs on it (RG-11 checks the platform)."""
    by = entry.get("steps_by_platform") or {}
    if platform and by.get(platform):
        return list(by[platform]), platform
    return list(entry.get("steps") or []), None


def note(topic: str, lang: str) -> dict:
    notes = library(lang)["notes"]
    return notes.get(topic) or notes.get(topic.split(" (")[0]) or notes["_schema_other"]


def note_steps(topics: list[str], lang: str, limit: int = STEP_LINES, platform: str | None = None) -> str:
    """One step per topic, in the card's order (and a topic's platform line when the site runs on it and there is room);
    past the limit the last step names the rest by their summaries."""
    steps_ = []
    for t in dict.fromkeys(topics):
        entry = note(t, lang)
        steps_.append(entry["step"])
        if platform and (entry.get("platform") or {}).get(platform):
            steps_.append(entry["platform"][platform])
    steps_ = list(dict.fromkeys(steps_))
    if len(steps_) > limit:
        rest = [lower_first(note(t, lang)["summary"], lang) for t in topics[limit - 1:]]
        more = fill(library(lang)["notes"]["_more"]["step"], list=join(list(dict.fromkeys(rest)), lang))
        steps_ = steps_[:limit - 1] + [more[:STEP_CHARS]]
    if len(steps_) == 1:
        steps_.append(library(lang)["generic"]["steps"][-1])
    return "\n".join(steps_)


def fits(text: str | None, limit: int | None) -> bool:
    return bool(text) and (limit is None or len(text) <= limit)


# ---------------------------------------------------------------- page 1

def _focus(summaries: list[str], lang: str) -> list[str]:
    return [lower_first(s, lang) for s in summaries if s]


def counts_band(counts: dict, lang: str) -> str | None:
    """DECISIONS 313: the problems by severity, as the first KPI counts them: "1 yüksek, 5 orta ve 11 düşük önemde sorun
    var". "Engelleyici" / "blocking" only when there is a Blocker. None when nothing S1-S4 is counted."""
    p = library(lang)["page1"]
    parts = [(int(counts.get(s) or 0), s) for s in ("S1", "S2", "S3", "S4") if int(counts.get(s) or 0)]
    if not parts:
        return None
    names = [f"{n} {p['count_names'][s]}" for n, s in parts]
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + p["levels_join"] + names[-1]
    total = sum(n for n, _ in parts)
    return fill(p["band_counts_one"] if total == 1 else p["band_counts"], list=listed)


def headline(severities: list[str], summaries: list[str], lang: str, *, pages_read: int = 1, limit: int = 90,
             counts: dict | None = None) -> str:
    """The report's one-line verdict from the problem cards' severities (S1-S4) and the top cards' summaries. With
    `counts` (problems by severity, DECISIONS 313) it says the exact numbers."""
    p = library(lang)["page1"]
    if not pages_read:
        return p["headline_unread"]
    if not severities:
        return p["headline_none"]
    exact = counts_band(counts, lang) if counts else None
    if exact:
        band = exact
    elif any(s in ("S1", "S2") for s in severities):
        band = p["band_high"]
    else:
        levels = [p["level_names"][s] for s in ("S3", "S4") if s in severities]
        band = fill(p["band"], levels=p["levels_join"].join(levels))
    focus = _focus(summaries, lang)
    for n in (2, 1):
        if len(focus) >= n:
            text = fill(p["headline"], band=band, focus=join(focus[:n], lang))
            if len(text) <= limit:
                return text
    return fill(p["headline_short"], band=band)


def assessment(summaries: list[str], has_confirm: bool, lang: str, *, limit: int = 190) -> str:
    p = library(lang)["page1"]
    focus = _focus(summaries, lang)
    tail = p["tail_confirm"] if has_confirm else p["tail_plain"]
    for key, n in (("assessment_three", 3), ("assessment_two", 2), ("assessment_one", 1)):
        if len(focus) >= n:
            text = fill(p[key], f1=focus[0], f2=focus[1] if n > 1 else "", f3=focus[2] if n > 2 else "", tail=tail)
            if len(text) <= limit:
                return text
    return p["assessment_none"]


def priority_text(entry: dict, confidence: str | None, manual: bool, lang: str, *, limit: int = 150) -> str:
    p = library(lang)["page1"]
    text = entry["explanation"]
    extra = p["priority_confirmed"] if manual else p["priority_estimated"] if confidence in ("estimated", "inferred") else None
    if extra and len(text) + 1 + len(extra) <= limit:
        return f"{text} {extra}"
    return text


def lead(entry: dict, lang: str, *, limit: int = 60) -> str:
    p = library(lang)["page1"]
    text = fill(p["lead"], title=lower_first(entry["title"], lang) if lang == "tr" else entry["title"])
    if len(text) <= limit:
        return text
    return fill(p["lead_short"], summary=lower_first(entry["summary"], lang))


def next_text(first: dict, rest: list[str], lang: str, *, limit: int = 200) -> str:
    p = library(lang)["page1"]
    if rest:
        for n in (2, 1):
            text = fill(p["next_text"], explanation=first["explanation"], rest=join(_focus(rest[:n], lang), lang))
            if len(text) <= limit:
                return text
    text = fill(p["next_text_alone"], explanation=first["explanation"])
    return text if len(text) <= limit else first["explanation"]


def caveat(*, reanalysis: bool, first_confidence: str | None, has_confirm: bool, has_cards: bool, lang: str,
           limit: int = 170) -> str:
    p = library(lang)["page1"]
    if not has_cards:
        return p["assessment_none"]
    base = (p["caveat_reanalysis"] if reanalysis else
            p["caveat_estimated"] if first_confidence in ("estimated", "inferred") else p["caveat_measured"])
    if has_confirm and len(base) + len(p["caveat_confirm"]) <= limit:
        return base + p["caveat_confirm"]
    return base


def followup(summaries: list[str], lang: str, *, limit: int = 170) -> str:
    p = library(lang)["page1"]
    focus = list(dict.fromkeys(_focus(summaries, lang)))
    for n in range(min(len(focus), 5), 0, -1):
        text = fill(p["followup"], list=join(focus[:n], lang))
        if len(text) <= limit:
            return text
    return fill(p["followup"], list="")


def confirm_title(entry: dict, scope: str | None, lang: str, *, limit: int = 90) -> str:
    text = fill(library(lang)["page1"]["confirm_title"], finding=entry["finding"], scope=scope) if scope else entry["finding"]
    return text if len(text) <= limit else entry["finding"]
