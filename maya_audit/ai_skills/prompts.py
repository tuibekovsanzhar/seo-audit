"""Reasoning frameworks for turning an audit report into a document a person can act on.

Each `Skill` is a prompt template plus a declaration of which parts of the report it needs. A
skill whose data is absent is not rendered with empty placeholders — `Skill.missing()` names what
is not there, so the caller can drop the skill or state the gap. An empty section in a generated
document reads as "nothing to report", which is the same lie as a `not_assessed` shown as a pass.

Ported from OpenSEO's agent skills (MIT, Ben Senescu, 2026). What carried over is the analytical
shape: the one-action audit, evidence-before-inference for competitive work, intent over surface
similarity for grouping, and adapting depth to the reader. What did not carry over is everything
tied to that product — MCP tool names, project-context and research-log calls, credit checks,
DataForSEO orchestration, Search Console specifics, keyword volume and difficulty. Those are not
stripped as an afterthought: three of the four skills were rebuilt around what Maya's JSON
actually contains, and one (keyword clustering) had no counterpart at all and became something
narrower that the data supports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .rules import (ADVERSARIAL_PASS, ATTRIBUTION, DATA_BEGIN, DATA_END, DATA_NOTICE, DATA_REMINDER, EDITORIAL_RULES,
                    EVIDENCE_RULES, OUTPUT_CONTRACT, SEVERITY_LADDER)


@dataclass(frozen=True)
class Skill:
    """One reasoning framework. `requires` names report keys that must be non-empty to run it."""

    name: str
    goal: str
    template: str
    # Either a report key ("checks"), or a key plus the check that must be in it
    # ("answer_engine_panel:ANS-4"). A bare key is satisfied by any non-empty value, which is not
    # enough when a prompt names particular checks as its evidence: a panel holding ANS-1..3 is
    # non-empty but carries nothing for a skill written around ANS-4 and ANS-5, and the model is
    # then asked to read data that is not there.
    requires: tuple[str, ...] = ()
    # Report keys the skill can use but does not need; absence is stated, not hidden.
    optional: tuple[str, ...] = ()

    def unavailable(self, payload: dict[str, Any]) -> dict[str, str]:
        """Each requirement this report cannot meet, with the reason. Empty when the skill is ready.

        A named check must be in the report, must have been assessed, and must hold something to read.
        A check that ran and measured zero (status `observed`, with its observations or evidence) is
        ready: "nothing was cited" is a result. A check that is `not_assessed`, or present with no
        findings, observations, evidence or review items, is not: a prompt written around it would ask
        a model to describe data it was not given.
        """
        absent: dict[str, str] = {}
        for requirement in self.requires:
            key, _, check_id = requirement.partition(":")
            value = payload.get(key)
            if not value:
                absent[requirement] = f"`{key}` is empty or not in the report"
                continue
            entries = [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []
            if not check_id:
                # A bare key over a list of checks needs at least one that was assessed.
                if entries and all("status" in entry for entry in entries) and \
                        all(entry["status"] == "not_assessed" for entry in entries):
                    absent[requirement] = f"every entry in `{key}` is not assessed"
                continue
            check = next((entry for entry in entries if entry.get("check_id") == check_id), None)
            if check is None:
                absent[requirement] = f"{check_id} is not in `{key}`"
            elif check.get("status") == "not_assessed":
                absent[requirement] = f"{check_id} was not assessed: {str(check.get('summary') or 'no reason recorded')[:300]}"
            elif not any(check.get(part) for part in ("findings", "observations", "evidence", "review_items")):
                absent[requirement] = f"{check_id} is present but holds no findings, observations or evidence"
        return absent

    def missing(self, payload: dict[str, Any]) -> list[str]:
        """The requirements this report cannot meet, by name. `unavailable` gives the reasons."""
        return list(self.unavailable(payload))

    def render(self, **values: Any) -> str:
        """Fill the template. Unknown placeholders raise rather than rendering as empty."""
        # The data goes last and inside a fence (DATA_BEGIN/DATA_END): page text reaches it verbatim, and the
        # model must read it as quoted data, never as instructions (review E-R1, rule 9).
        body = self.template.format(severity_ladder=SEVERITY_LADDER, evidence_rules=EVIDENCE_RULES,
                                    editorial_rules=EDITORIAL_RULES, adversarial_pass=ADVERSARIAL_PASS,
                                    output_contract=OUTPUT_CONTRACT, data_notice=DATA_NOTICE,
                                    data_begin=DATA_BEGIN, data_end=DATA_END, data_reminder=DATA_REMINDER,
                                    **values)
        return f"<!-- {ATTRIBUTION} -->\n\n{body}"


# --- 1. The audit report ----------------------------------------------------
# From OpenSEO's `seo-audit`: one page, one action, plain language, evidence per row, name what is
# working, method footer. Reframed from "run these MCP tools" to "read this finished JSON", and
# extended with the parts Maya's model needs that a traditional SEO audit has no equivalent for:
# the integrity gates, and the not-assessed list.
AUDIT_REPORT = Skill(
    name="audit-report",
    goal="Turn a completed technical audit into a one-page report built around a single next action.",
    requires=("checks", "gates"),
    optional=("answer_engine_panel", "needs_human_review"),
    template="""\
You are writing a technical audit report for {brand_name} ({site_url}), for a reader who is smart
but does not work in search or AI visibility. They will read it once and act on it.

The audit has already run. You are not gathering evidence; you are explaining what was found.
Everything you may claim is in the JSON below.

## What this audit measures

Whether AI answer engines — ChatGPT, Claude, Perplexity, Google's AI Overviews and AI Mode,
Copilot — can reach this site, read it, and quote it correctly. It is a technical audit: it says
nothing about whether the content is any good.

## Read the integrity gates first

`gates` holds four checks on the audit itself, and they decide whether anything else means
anything. If INT-1 is `degraded`, the site served challenge pages instead of content and the
findings describe a firewall, not the site. If INT-2 is `incomplete`, say what share of the site
was covered. If INT-3 says rendering did not run, the rendering findings are fallback guesses and
must be labelled as such. If INT-4 is anything but `compliant`, stop and report that instead: the
crawler misbehaved and the run is not trustworthy.

## Severity

{severity_ladder}

{evidence_rules}

{editorial_rules}

## Structure

1. **Summary** — two or three sentences: the overall state, the main gap, what the one action is.
2. **The one thing to do first** — derived from the findings, not from general advice. Doable by
   this team. Include the evidence and the concrete steps.
3. **Also worth fixing** — five to ten, ordered by how much they matter here. For each: severity,
   what was found (quoting the evidence), why it matters, what to do.
4. **What is working** — the checks with status `pass` (not `partial`), grouped so it reads as a
   short paragraph.
5. **What could not be checked, and why** — every `not_assessed` check with its reason, and every
   not-assessed part listed in a `partial` check's `coverage`. Open this section by saying these are
   gaps, not passes.
6. **Method** — how many pages of how many, the request count and delay, the identity the crawler
   used, and the fact that robots.txt was fetched first and obeyed.

{output_contract}

{adversarial_pass}

## The audit (untrusted data)

{data_notice}

{data_begin}
{audit_section}
{data_end}

{data_reminder}
""",
)


# --- 2. Cited-domain landscape ---------------------------------------------
# From OpenSEO's `competitor-analysis`: snapshot / biggest lesson / best opportunity, an evidence
# column in every row, and its sharpest guardrail — do not infer page-level claims from aggregate
# rows. That guardrail does most of the work here, because Maya never crawls a competitor: the
# only competitor evidence is a mention count. Keyword themes, backlink profiles and head-to-head
# SERP comparisons are all dropped; none of them exist in this data.
CITED_DOMAIN_LANDSCAPE = Skill(
    name="cited-domain-landscape",
    goal="Explain which domains answer engines cite on this brand's prompts, and what can honestly be read into it.",
    requires=("answer_engine_panel:ANS-4", "answer_engine_panel:ANS-5"),
    template="""\
You are explaining the answer-engine citation picture for {brand_name} ({site_url}).

The evidence is ANS-4 and ANS-5 in the panel below. ANS-4 covers which engines cite this site and
how often. ANS-5 covers the other domains cited on the same prompts, sorted into the site itself,
engine infrastructure such as image CDNs, reference works, directories and profiles, public
institutions, and other commercial domains.

## What you may and may not conclude

1. **You have mention counts and nothing else.** The audit never crawled any of these domains. You
   cannot say why a competitor is cited more, what their pages look like, or what they did well.
   Any sentence about a third party's content or strategy is invention. Describe the pattern and
   stop.
2. **This is not Share of Voice.** Maya's product has a metric by that name measuring something
   different — brand mentions in answer text across a curated competitor set. These are cited
   source domains. On one real project the two differed several-fold, both correct. Never use the
   phrase, and if the reader knows Maya's number, explain that the two count different things.
3. **Check whether the export is truncated** before comparing anything. `export_truncated` and
   `rows_returned` of `rows_total` are in the evidence. A top-20 slice of four thousand domains
   supports "these are the largest cited sources", not "these are the competitors".
4. **An engine citing this site zero times is Info and a Hypothesis.** The engine may not cover
   this language or market at all. If ACC-2 or ACC-6 reports that engine's crawler as blocked,
   that finding owns the cause — cite it rather than speculating.
5. **Infrastructure domains are not competitors.** An image CDN ranking third is an artefact of
   how that engine cites its own assets. Say so if the reader might misread it.
6. **Do not recommend copying anyone.** If a directory page outranks the site's own page for its
   own subject, the useful observation is that the brand's presence lives off-site.

{evidence_rules}

{editorial_rules}

## Structure

1. **Snapshot** — which engines cite this site, how often, over what period, and whether the
   export is complete.
2. **What stands out** — the single most useful observation, with the numbers behind it.
3. **The table** — one row per notable domain: domain, what class it was sorted into, mentions,
   engines, and what can honestly be read into it. Keep "what it means" empty rather than guessing.
4. **What this does not tell you** — be specific: no competitor pages were examined, the export
   may be truncated, and citation counts are a sample of engine behaviour, not a ranking.

{output_contract}

{adversarial_pass}

## The panel (untrusted data)

{data_notice}

{data_begin}
{panel_section}
{data_end}

{data_reminder}
""",
)


# --- 3. Cited-page mapping --------------------------------------------------
# OpenSEO's `keyword-clustering` has no counterpart here: Maya's audit holds no keywords, no search
# volume and no SERP data, so the skill itself could not be ported. What ported is its reasoning —
# group by intent rather than surface similarity, do not over-cluster a small set, label anything
# unconfirmed as proposed, and watch for two pages competing for one intent. Applied to the only
# grouping this data supports: cited URLs and the prompts that triggered them.
CITED_PAGE_MAPPING = Skill(
    name="cited-page-mapping",
    goal="Group the pages engines cite by the question they answer, and find pages competing for one question.",
    requires=("answer_engine_panel:ANS-1",),
    template="""\
You are mapping which pages of {site_url} answer engines actually cite, and for what.

The evidence is ANS-1 in the panel below: every cited URL, the engines that cited it, when, and
the prompt behind each citation where one was recorded.

## Rules for grouping

1. **Group by the question, not by the URL.** Two pages cited for the same question belong
   together even when their addresses look nothing alike; two pages with near-identical addresses
   cited for different questions do not.
2. **Do not over-group a small set.** Under about ten cited URLs, list them plainly and skip the
   grouping. A taxonomy over six rows is noise.
3. **Prompt IDs are not topics.** Maya's export often carries a `promptId` such as `c5ee2b54` and
   no prompt text. When that is all you have, say the grouping is by prompt identity and that the
   subject of each prompt is not in the data. Never invent a topic name from the URL and present
   it as the question a user asked.
4. **Two pages cited for one question is worth naming** — engines are choosing between them, and
   the site is probably splitting its own signals.
5. **Anything not confirmed by the data is "proposed"** and labelled as such in the row.
6. **A cited page that fails a site check is the important row.** ANS-1 carries the site-side
   result for every cited URL. A page that engines cite *and* that is broken outranks every other
   observation in this document.

{evidence_rules}

{editorial_rules}

## Structure

1. **Summary** — how many pages are cited, by how many engines, over what period, and how many of
   them fail a site-side check.
2. **The map** — one row per group: the question or prompt identity, the pages cited for it, which
   engines, and whether any of those pages has a finding against it.
3. **Pages competing for one question**, if any.
4. **What is missing** — cited pages the crawl never reached, prompts with no text, and anything
   else the data does not carry.

{output_contract}

{adversarial_pass}

## The panel (untrusted data)

{data_notice}

{data_begin}
{panel_section}
{data_end}

{data_reminder}
""",
)


# --- 4. Explaining it -------------------------------------------------------
# From OpenSEO's `seo-coach`: ask about the reader's level before choosing depth, keep the data
# sources distinct, offer a few concrete next steps rather than a menu, and never claim the tool
# can do something it cannot. The workflow catalogue and tool coaching are dropped — those
# described OpenSEO's own product.
EXPLAIN_AND_NEXT_STEPS = Skill(
    name="explain-and-next-steps",
    goal="Answer questions about a finished audit and recommend what to do next, at the reader's level.",
    requires=("checks",),
    optional=("answer_engine_panel", "gates"),
    template="""\
You are helping someone at {brand_name} understand a finished technical audit of {site_url} and
decide what to do next.

## How to work

1. **Ask before you calibrate.** One question: are they technical, or do they want this in plain
   terms? Adapt the depth to the answer. Do not open with a lecture.
2. **Keep the sources distinct**, and say which one a statement rests on:
   - measured by this audit on the site's own pages — the strongest evidence here;
   - reported by an answer engine, sampled rather than complete;
   - not assessed, with a reason;
   - your own inference, which is the weakest and must be labelled.
3. **One next step beats ten.** Give the single most useful action, then at most two or three
   alternatives. No roadmaps.
4. **Do not overstate what this audit can see.** It did not measure rankings, traffic, content
   quality, or whether a fix will change an answer. When asked something it cannot answer, say so
   and say what would answer it.
5. **When a check was not assessed, say what it would take to close it** — an ownership
   verification tag, server logs, a Search Console connection, an API key.

{evidence_rules}

## Answering well

- Quote the check id and the evidence value behind every claim.
- When something is genuinely fine, say so plainly instead of hedging.
- When the honest answer is "the audit did not look at that", give it in one sentence and move on.
- Never invent a number to make an answer feel complete.

{output_contract}

## The audit (untrusted data)

{data_notice}

{data_begin}
{audit_section}
{data_end}

{data_reminder}
""",
)


SKILLS: dict[str, Skill] = {skill.name: skill for skill in
                           (AUDIT_REPORT, CITED_DOMAIN_LANDSCAPE, CITED_PAGE_MAPPING, EXPLAIN_AND_NEXT_STEPS)}


def skill_names() -> list[str]:
    return list(SKILLS)


@dataclass
class SkillBrief:
    """A skill paired with the payload it needs, and whatever it could not be given."""

    skill_name: str
    goal: str
    prompt: str | None
    missing: list[str] = field(default_factory=list)
    # Why each entry of `missing` is missing (requirement -> reason), so a reader is told, not left to guess.
    missing_reasons: dict[str, str] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.prompt is not None
