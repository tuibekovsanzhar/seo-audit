"""Answers to questions about one audit, and the boundary a future AI assistant would sit behind.

`DeterministicAssistant` is the only implementation and is what runs. No model is involved: a question is
matched against fixed intents and against the words of the report's own findings, and the answer is assembled
from the report. A question the report cannot answer is told so and offered what can be answered. Questions
about rankings, mention rates, sentiment, traffic or visibility scores always get "this audit does not measure
that".

`AssistantProvider` documents what any other implementation would be given: the question and an
`AssistantContext`, which exposes a bounded summary, finding and check lookups by id, and nothing else. The
saved crawl is not handed over, and neither website text nor an assistant's output can start an audit,
approve a cost or change a finding (docs/ASSISTANT.md).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from . import summary
from .strings import has, t

TOP = 5

# Things a technical audit does not measure. Checked first, so no later rule can answer them by accident.
_NOT_MEASURED = re.compile(
    r"\b(rank(ing|ings|ed|s)?|position(s)?|mention(s|ed)?\s*(rate|share)?|share of voice|sentiment|"
    r"visibility\s*(score|index)?|how visible|traffic|clicks?|impressions?|revenue|conversions?|"
    r"sıralama|görünürlük|duygu|bahsed\w*)\b", re.IGNORECASE)
_CHECK_ID = re.compile(r"\b(ACC|IDX|RND|STR|TSEO|PRF|ANS|INT)[- ]?(\d{1,2})\b", re.IGNORECASE)
_ROLES = (("developer", re.compile(r"\b(developers?|devs?|engineers?|engineering|geliştirici|yazılımcı)\b", re.IGNORECASE)),
          ("content", re.compile(r"\b(content|writers?|editors?|copy|içerik|editör)\b", re.IGNORECASE)),
          ("seo", re.compile(r"\b(seo|search (team|specialist)s?|marketing)\b", re.IGNORECASE)))
_SEVERITY_WORDS = (("S1", re.compile(r"\b(s1|blockers?)\b", re.IGNORECASE)), ("S2", re.compile(r"\b(s2|high)\b", re.IGNORECASE)),
                   ("S3", re.compile(r"\b(s3|medium)\b", re.IGNORECASE)), ("S4", re.compile(r"\b(s4|low)\b", re.IGNORECASE)),
                   ("Info", re.compile(r"\b(info|notes?|informational)\b", re.IGNORECASE)))

_INTENTS: list[tuple[str, re.Pattern[str]]] = [
    ("compare", re.compile(r"\b(compar\w*|last audit|previous audit|since last|what changed|difference|karşılaştır\w*)\b", re.IGNORECASE)),
    ("critical", re.compile(r"\b(critical|urgent|serious|most severe|kritik|acil)\b", re.IGNORECASE)),
    ("top", re.compile(r"\b(top|biggest|main|worst|first) (issue|problem|finding)|explain the top|en önemli sorun\b", re.IGNORECASE)),
    ("plan", re.compile(r"\b(action plan|plan|to-?do|what (should|do) (i|we) (do|fix)|where (do i|to) start|priorit\w*|"
                        r"fix first|eylem plan\w*|önce(lik)?)\b", re.IGNORECASE)),
    ("coverage", re.compile(r"\b(not (checked|assessed|covered)|could ?n[o']t (be )?check\w*|coverage|missing|skipped|"
                            r"left out|unassessed|partial\w*|kontrol edilemedi|kapsam)\b", re.IGNORECASE)),
    ("pages", re.compile(r"\b(which|what) (pages?|urls?)|pages? (are )?affected|affected pages?|worst pages?|hangi sayfa\w*\b", re.IGNORECASE)),
    ("summary", re.compile(r"\b(summar\w*|overview|overall|in short|tl;?dr|özet)\b", re.IGNORECASE)),
    ("cost", re.compile(r"\b(cost|spen[dt]|paid|charged?|budget|allowance|dataforseo|backlinks?|maliyet|ücret)\b", re.IGNORECASE)),
    ("downloads", re.compile(r"\b(download|pdf|export|markdown|json|indir)\b", re.IGNORECASE)),
]

# A topic word -> the check area that speaks to it.
_AREA_WORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(javascript|js|render\w*|client[- ]side|spa|react|vue|angular)\b", re.IGNORECASE), "RND"),
    (re.compile(r"\b(crawler|crawlers|bot|bots|gptbot|robots(\.txt)?|blocked|block|waf|firewall|ai (search|crawler)\w*)\b",
                re.IGNORECASE), "ACC"),
    (re.compile(r"\b(index\w*|canonical\w*|sitemap\w*|redirect\w*|noindex|https|tls|certificate|404|hreflang)\b",
                re.IGNORECASE), "IDX"),
    (re.compile(r"\b(speed|slow|fast|performance|latency|timeout|response time|hız)\b", re.IGNORECASE), "PRF"),
    (re.compile(r"\b(schema|structured data|json-?ld|heading|headings|title|titles|meta|description\w*|markup|alt text|anchor)\b",
                re.IGNORECASE), "STR"),
]

_WORD = re.compile(r"[a-z0-9çğıöşü][a-z0-9çğıöşü.\-]{2,}", re.IGNORECASE)
_STOP_WORDS = frozenset("the and for are was what which with that this from have does not can could would should about "
                        "how why who your you our any all there page pages site website audit fix problem problems issue "
                        "issues tell show give more please only explain bir ve ile için".split())


@dataclass
class AssistantContext:
    """Everything an assistant may read about one audit. Bounded on purpose."""
    view: dict[str, Any]                                   # summary.build: counts, top five, coverage, panels
    report: dict[str, Any]                                 # read through summary.* only
    compare: Callable[[], dict[str, Any] | None]           # with the previous audit of the same site, if any
    affected: Callable[[str], list[str]]                   # every affected page of one finding


class AssistantProvider(Protocol):
    def answer(self, question: str, context: AssistantContext) -> dict[str, Any]: ...


def _reply(intent: str, text: str, items: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    return {"intent": intent, "text": text, "items": items or [], **extra}


def _line(row: dict[str, Any]) -> str:
    return t("follow.item", check=row["check_id"], title=row.get("title_shown") or row["title"], severity=row["severity_label"],
             scope=row["affects"], fix=row.get("fix_shown") or row["fix"])


def _plan(ctx: AssistantContext, role: str | None) -> dict[str, Any]:
    plan = summary.action_plan(ctx.report, role)
    if not plan["total"]:
        return _reply("plan", t("follow.plan.none.role", role=plan["role_label"]) if role else t("follow.first.none"))
    items = [f"{group['label']}: {len(group['items'])}" for group in plan["groups"] if group["items"]]
    first = next((row for group in plan["groups"] for row in group["items"] if row["requires_fix"]), None)
    lead = t("follow.plan.lead.role", role=plan["role_label"]) if role else t("follow.plan.lead")
    return _reply("plan", lead, items + ([t("follow.plan.start", line=_line(first))] if first else []),
                  card={"type": "action_plan", "role": role}, finding_ids=[first["id"]] if first and not first.get("action_kind") else [])


def _severity(ctx: AssistantContext, levels: list[str], intent: str) -> dict[str, Any]:
    found = summary.search(ctx.report, severity=levels, limit=TOP)
    labels = ", ".join(t(f"result.severity.{level}") for level in levels)
    if not found["total"]:
        return _reply(intent, t("follow.severity.none", levels=labels))
    return _reply(intent, t("follow.severity.lead", levels=labels, total=found["total"]), [_line(r) for r in found["items"]],
                  finding_ids=[r["id"] for r in found["items"]], card={"type": "findings", "severity": levels})


def _top(ctx: AssistantContext) -> dict[str, Any]:
    row = ctx.view["first_action"] or (ctx.view["top"][0] if ctx.view["top"] else None)
    if row is None:
        return _reply("top", t("follow.first.none"))
    pages = (ctx.affected(row["id"])[:TOP] if not row.get("action_kind") else []) or row["sample_pages"]
    items = [t("follow.top.what", severity=row["severity_label"], meaning=row["severity_meaning"]),
             t("follow.top.why", why=row["why"]), t("follow.top.fix", fix=row.get("fix_shown") or row["fix"]),
             t("follow.top.confidence", confidence=row["confidence_label"]),
             t("follow.top.estimates", owner=row["estimates"]["owner_label"], effort=row["estimates"]["effort_label"]),
             (row["source"]["notice"] if row.get("action_kind") else
              t("follow.top.pages", count=row["pages_total"], pages=", ".join(pages)))]
    return _reply("top", t("follow.top.lead", check=row["check_id"], title=row.get("title_shown") or row["title"]), items, finding_ids=[] if row.get("action_kind") else [row["id"]])


def _check(ctx: AssistantContext, check_id: str) -> dict[str, Any]:
    found = summary.check_view(ctx.report, check_id)
    if found is None:
        return _reply("check", t("follow.check.unknown", check=check_id))
    items = [found["why"]] + [_line(row) for row in found["findings"][:TOP]]
    items += [t("follow.coverage.item", check=check_id, part=part.get("part_shown") or part.get("part"), reason=part.get("reason_shown") or part.get("reason"))
              for part in found["not_assessed"][:3]]
    key = f"result.status.{found['status']}"
    status = t(key) if has(key) else str(found["status"])  # a gate has a state of its own, shown as it is
    return _reply("check", t("follow.check.lead", check=check_id, title=found.get("title_shown") or found["title"], status=status, summary=found.get("summary_shown") or found["summary"]),
                  items, finding_ids=[row["id"] for row in found["findings"][:TOP]])


def _coverage(ctx: AssistantContext) -> dict[str, Any]:
    coverage = ctx.view["coverage"]
    rows = [t("follow.coverage.item", check=gap["checks_label"], part=gap.get("part_shown") or gap["part"], reason=gap.get("reason_shown") or gap["reason"])
            for gap in coverage["gaps"][:12]]
    if coverage["read_only_note"]:
        rows.insert(0, coverage["read_only_note"])
    if coverage["sampled_note"]:
        rows.append(coverage["sampled_note"])
    return _reply("coverage", t("follow.coverage.lead") if len(rows) > 1 else t("follow.coverage.none"), rows)


def _pages(ctx: AssistantContext, question: str) -> dict[str, Any]:
    named = _CHECK_ID.search(question)
    if named:
        found = summary.check_view(ctx.report, f"{named.group(1).upper()}-{named.group(2)}")
        rows = (found or {}).get("findings") or []
        if rows:
            pages = ctx.affected(rows[0]["id"])
            return _reply("pages", t("follow.pages.finding", title=rows[0].get("title_shown") or rows[0]["title"], count=len(pages) or rows[0]["pages_total"]),
                          pages[:10], finding_ids=[rows[0]["id"]])
    counts: Counter[str] = Counter()
    for row in summary.search(ctx.report, limit=500)["items"]:
        if row["requires_fix"]:
            counts.update(ctx.affected(row["id"]) or row["sample_pages"])
    if not counts:
        return _reply("pages", t("follow.pages.none"))
    return _reply("pages", t("follow.pages.lead"), [t("follow.pages.row", url=url, count=n) for url, n in counts.most_common(10)])


def _summary(ctx: AssistantContext) -> dict[str, Any]:
    counts = ctx.view["counts"]
    return _reply("summary", t("follow.summary", outcome=ctx.view["outcome"]["label"] or "", pages=counts["pages_checked"],
                               s1=counts["by_severity"]["S1"], s2=counts["by_severity"]["S2"], s3=counts["by_severity"]["S3"],
                               s4=counts["by_severity"]["S4"], review=counts["needs_review"], gaps=counts["not_checked"]),
                  [note for note in [(ctx.view.get("status") or {}).get("summary"), ctx.view["coverage"]["sampled_note"]] if note])


def _cost(ctx: AssistantContext) -> dict[str, Any]:
    backlinks = ctx.view.get("backlinks")
    if not backlinks:
        return _reply("cost", t("follow.cost.none"))
    return _reply("cost", backlinks["spent_line"], [f"{c['title']}: {c['summary']}" for c in backlinks["checks"]])


def _compare(ctx: AssistantContext) -> dict[str, Any]:
    result = ctx.compare()
    if result is None:
        return _reply("compare", t("follow.compare.none"))
    items = [d["message"] for d in result["differences"]]
    if result["caution"]:
        items.append(result["caution"])
    return _reply("compare", result["summary_line"], items, card={"type": "comparison"})


def _area(ctx: AssistantContext, area: str) -> dict[str, Any] | None:
    group = next((a for a in ctx.view["areas"] if a["area"] == area), None)
    if group is None:
        return None
    found = summary.search(ctx.report, area=area, limit=TOP)
    rows = [_line(row) for row in found["items"]]
    rows += [f"{c['check_id']} {c['title']}: {c['summary']}" for c in group["checks"] if c["status"] == "not_assessed"][:TOP]
    key = "follow.area.lead" if group["problems"] else "follow.area.clean"
    return _reply(f"area:{area}", t(key, area=group["label"], problems=group["problems"], notes=group["notes"],
                                    not_checked=group["not_checked"]), rows, finding_ids=[r["id"] for r in found["items"]])


def _match(ctx: AssistantContext, question: str) -> dict[str, Any] | None:
    """Findings whose own wording shares the question's words."""
    words = {w.lower() for w in _WORD.findall(question)} - _STOP_WORDS
    scored = []
    for row in summary.search(ctx.report, limit=500)["items"]:
        text = f"{row['title']} {row['fix']} {row['check_id']} {row.get('title_shown') or ''} {row.get('fix_shown') or ''}".lower()
        hits = sum(word in text for word in words)
        if hits:
            scored.append((hits, row))
    if not scored:
        return None
    best = [row for _, row in sorted(scored, key=lambda pair: -pair[0])[:TOP]]
    return _reply("match", t("follow.match.lead"), [_line(row) for row in best], finding_ids=[row["id"] for row in best])


class DeterministicAssistant:
    """Rule-based answers from the report. Always returns something true, or says it cannot answer."""

    def answer(self, question: str, context: AssistantContext) -> dict[str, Any]:
        question = question.strip()
        suggestions = context.view["follow_ups"]
        if _NOT_MEASURED.search(question):
            return _reply("not_measured", t("follow.not_measured"), suggestions=suggestions)
        role = next((name for name, pattern in _ROLES if pattern.search(question)), None)
        named = _CHECK_ID.search(question)
        for intent, pattern in _INTENTS:
            if not pattern.search(question):
                continue
            if intent == "compare":
                return _compare(context)
            if intent == "critical":
                return _severity(context, ["S1", "S2"], "critical")
            if intent == "top":
                return _top(context)
            if intent == "plan":
                return _plan(context, role)
            if intent == "coverage":
                return _coverage(context)
            if intent == "pages":
                return _pages(context, question)
            if intent == "summary":
                return _summary(context)
            if intent == "cost":
                return _cost(context)
            if intent == "downloads":
                return _reply("downloads", t("follow.downloads"))
        if named:
            return _check(context, f"{named.group(1).upper()}-{named.group(2)}")
        if role:
            return _plan(context, role)
        levels = [level for level, pattern in _SEVERITY_WORDS if pattern.search(question)]
        if levels:
            return _severity(context, levels, "severity")
        for pattern, area in _AREA_WORDS:
            if pattern.search(question):
                found = _area(context, area)
                if found:
                    return found
        return _match(context, question) or _reply("unknown", t("follow.unknown"), suggestions=suggestions)
