"""Read a model's document against the brief it was written from, and flag what the evidence does not carry.

Every prompt ends with an output contract (`rules.OUTPUT_CONTRACT`): claims cite a check id and, for one finding,
its finding id; numbers are copied from the data; no score or grade. Until now nothing read the answer, so the
contract was a request (review E-R3). This is the reading half. It is deliberately mechanical and errs towards
flagging: a flag is a line for a person to look at, not a verdict that the document is wrong, and a document with
no flags is one that passed these three tests, not one that is true.

What it flags, one line of the document at a time:
  - `unknown_check` / `unknown_finding` / `finding_check_mismatch`: a citation naming an id the audit does not
    have, or a finding id cited under another check;
  - `uncited_claim`: a line that states something checkable (a number, a severity, a check id in passing) and
    carries no citation;
  - `number_not_in_report`: a number that appears nowhere in the audit data;
  - `score`: anything shaped like a score, grade or rating.

Usage: python -m maya_audit.ai_skills.check_output brief.json document.md [--report report.json] [--json]
Exit 0 with no flags, 1 with flags, 2 when an input cannot be read.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .rules import CHECK_ID_PATTERN, DATA_BEGIN, DATA_END, FINDING_ID_PATTERN

# One citation: [CHECK] or [CHECK · FINDING]; "·", ":" and "/" are all accepted between the two, and several
# citations may share one pair of brackets separated by ";" or ",".
_ITEM = rf"(?:{CHECK_ID_PATTERN})(?:\s*[·:/|]\s*{FINDING_ID_PATTERN})?"
CITATION_RE = re.compile(rf"\[\s*({_ITEM}(?:\s*[;,]\s*{_ITEM})*)\s*\]")
_ITEM_RE = re.compile(rf"({CHECK_ID_PATTERN})(?:\s*[·:/|]\s*({FINDING_ID_PATTERN}))?")
_FINDING_RE = re.compile(rf"\b{FINDING_ID_PATTERN}\b")
_CHECK_RE = re.compile(rf"\b{CHECK_ID_PATTERN}\b")
_URL_RE = re.compile(r"https?://\S+|\b[\w.-]+\.[a-z]{2,}(?:/\S*)?", re.IGNORECASE)
# Numbers as a reader writes them: 1,234 · 1.234 · 35.9 · 35,9 · 12%. Dates and times are taken apart into their
# parts, which the data holds in its own timestamps.
_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*")
_SEVERITY_RE = re.compile(r"\b(?:S[1-4]|Blocker|High|Medium|Low|Kritik|Yüksek|Orta|Düşük)\b")
_SCORE_RE = re.compile(
    r"\b\d{1,3}\s*/\s*(?:10|100)\b"
    r"|\b\d{1,3}\s+out\s+of\s+(?:10|100)\b"
    r"|\b(?:score|scored|grade|graded|rating|rated|skor|puan)\s*(?:of|:|=|is|was)?\s*\d"
    r"|\bgrade\s*:?\s*[A-F][+-]?(?![\w])"
    r"|\b\d{1,3}\s*%\s*(?:healthy|health|optimi[sz]ed|complete|done|of the way|sağlıklı)",
    re.IGNORECASE)
# List numbering and step numbers a writer adds; never evidence.
_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*+>]\s+)?(?:#+\s*)?(?:\d+[.)]\s+)?")


@dataclass
class Flag:
    line: int
    kind: str
    detail: str
    text: str


@dataclass
class Evidence:
    """What the document may cite: check ids, finding ids (and which check owns each), and numbers."""

    checks: set[str]
    findings: dict[str, str]
    numbers: set[str]


def _walk(value: Any, out: list[Any]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            out.append(key)
            _walk(item, out)
    elif isinstance(value, list):
        for item in value:
            _walk(item, out)
    else:
        out.append(value)


def _normal_number(text: str) -> set[str]:
    """Spellings of one written number that the data could hold: 1,234 and 1.234 as 1234, 35,9 as 35.9."""
    forms = {text}
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", text):
        forms.add(re.sub(r"[.,]", "", text))
    if re.fullmatch(r"\d+,\d+", text):
        forms.add(text.replace(",", "."))
    out = set()
    for form in forms:
        out.add(form)
        try:
            number = float(form)
        except ValueError:
            continue
        out.add(repr(number))
        if number == int(number):
            out.add(str(int(number)))
        out.add(f"{number:g}")
    return out


def evidence_from(*sources: dict[str, Any]) -> Evidence:
    """Collect ids and numbers from report-shaped dicts (a report, or a brief's `audit` payload)."""
    checks: set[str] = set()
    findings: dict[str, str] = {}
    numbers: set[str] = set()
    for source in sources:
        for key in ("gates", "checks", "answer_engine_panel"):
            for check in source.get(key) or []:
                if not isinstance(check, dict) or not isinstance(check.get("check_id"), str):
                    continue
                checks.add(check["check_id"])
                for finding in (check.get("findings") or []) + (check.get("review_items") or []):
                    if isinstance(finding, dict) and isinstance(finding.get("id"), str):
                        findings[finding["id"]] = check["check_id"]
                for fid in check.get("findings_omitted_ids") or []:
                    if isinstance(fid, str):
                        findings[fid] = check["check_id"]
        for key in ("findings_in_priority_order", "needs_human_review"):
            for fid in source.get(key) or []:
                if isinstance(fid, str):
                    match = re.match(rf"({CHECK_ID_PATTERN})-", fid)
                    findings.setdefault(fid, match.group(1) if match else "")
        values: list[Any] = []
        _walk(source, values)
        for value in values:
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, (int, float)):
                numbers |= _normal_number(repr(value)) | _normal_number(str(value))
            elif isinstance(value, str):
                for token in _NUMBER_RE.findall(value):
                    numbers |= _normal_number(token)
    return Evidence(checks, findings, numbers)


def data_from_brief(brief: dict[str, Any]) -> dict[str, Any] | None:
    """The audit payload a brief carries: its `audit` object, or (inline mode) the JSON inside a prompt's fence."""
    if isinstance(brief.get("audit"), dict):
        return brief["audit"]
    for skill in brief.get("skills") or []:
        prompt = (skill or {}).get("prompt") or ""
        if DATA_BEGIN not in prompt or DATA_END not in prompt:
            continue
        block = prompt.split(DATA_BEGIN, 1)[1].split(DATA_END, 1)[0].strip()
        if block.startswith("```"):
            block = block.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("checks") is not None:
            return data
    return None


def check_document(document: str, evidence: Evidence) -> list[Flag]:
    flags: list[Flag] = []
    in_code = False
    for number, raw in enumerate(document.splitlines(), start=1):
        line = raw.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line or line.startswith("<!--") or re.fullmatch(r"[|:\-\s]+", line):
            continue
        heading = line.startswith("#")

        def flag(kind: str, detail: str) -> None:
            flags.append(Flag(number, kind, detail, line[:200]))

        cited = False
        for citation in CITATION_RE.finditer(line):
            for check_id, finding_id in _ITEM_RE.findall(citation.group(1)):
                cited = True
                if check_id not in evidence.checks:
                    flag("unknown_check", f"{check_id} is not a check in this audit")
                if finding_id:
                    owner = evidence.findings.get(finding_id)
                    if owner is None:
                        flag("unknown_finding", f"{finding_id} is not a finding in this audit")
                    elif owner and owner != check_id:
                        flag("finding_check_mismatch", f"{finding_id} belongs to {owner}, cited under {check_id}")

        if _SCORE_RE.search(line):
            flag("score", "reads as a score, grade or rating; the audit has none (rule 3)")

        # What is left once citations, ids, URLs and list numbering are taken out is the prose the numbers are in.
        prose = CITATION_RE.sub(" ", line)
        prose = _FINDING_RE.sub(" ", prose)
        bare_checks = _CHECK_RE.findall(prose)
        prose = _CHECK_RE.sub(" ", prose)
        prose = _URL_RE.sub(" ", prose)
        prose = _SEVERITY_RE.sub(" ", prose) if not heading else prose
        prose = _LIST_PREFIX_RE.sub("", prose, count=1)
        numbers = _NUMBER_RE.findall(prose)
        for written in numbers:
            if not (_normal_number(written) & evidence.numbers):
                flag("number_not_in_report", f"{written} does not appear in the audit data")

        if heading or cited:
            continue
        if numbers or bare_checks or _SEVERITY_RE.search(line):
            flag("uncited_claim", "states something checkable but carries no [CHECK-ID] citation")
    return flags


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m maya_audit.ai_skills.check_output",
                                     description="Check a model's document against the LLM brief it was written from.")
    parser.add_argument("brief", help="the brief written by `maya-audit crawl --llm-brief`")
    parser.add_argument("document", help="the model's document (Markdown or plain text)")
    parser.add_argument("--report", help="the full report.json; adds ids and numbers the brief's payload left out")
    parser.add_argument("--json", action="store_true", help="print the flags as JSON")
    args = parser.parse_args(argv)
    try:
        brief = json.loads(Path(args.brief).read_text(encoding="utf-8-sig"))
        document = Path(args.document).read_text(encoding="utf-8-sig")
        report = json.loads(Path(args.report).read_text(encoding="utf-8-sig")) if args.report else None
    except (OSError, ValueError) as exc:
        print(f"cannot read input: {exc}", file=sys.stderr)
        return 2
    sources = [source for source in (data_from_brief(brief), report) if isinstance(source, dict)]
    if not sources:
        print("the brief carries no audit data (no `audit` object and no fenced JSON); pass --report report.json",
              file=sys.stderr)
        return 2
    flags = check_document(document, evidence_from(*sources))
    if args.json:
        print(json.dumps([asdict(flag) for flag in flags], indent=2, ensure_ascii=False))
    else:
        for item in flags:
            print(f"line {item.line}: {item.kind}: {item.detail}\n    {item.text}")
        print(f"{len(flags)} flag(s)" + ("" if flags else "; this is not proof the document is correct"))
    return 1 if flags else 0


if __name__ == "__main__":
    sys.exit(main())
