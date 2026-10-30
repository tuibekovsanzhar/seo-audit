"""What a model is given to read: the analysis payload, bounded and fenced.

`report.analysis_payload` already drops the raw crawl. What is left still grows with the site: each check keeps
every finding and every list in its evidence (heading lists, URL samples, cited pages), so a 9-page fake site
gives a 219 KB payload and a large site gives more, with no ceiling at all (review E-R2). A model asked to read
that either truncates it silently or loses the rules at the top of the prompt.

The budget here is deliberately dumb and visible: inside each gate, check and panel entry, every list keeps its
first `LIST_LIMIT` items and says how many it dropped. A check's own findings are the one list cut by priority
rather than position, so an S1 is never the item left out. Lists outside the checks (`findings_in_priority_order`,
`needs_human_review`) are left whole: they are short ids, and they are what a cited finding id is checked against.

The same pass neutralises the data-block markers. Page text reaches the payload verbatim (a title, an H1), and a
page that wrote `<<<MAYA_AUDIT_DATA_END>>>` into its title could otherwise close the fence around the data and
have the rest of its text read as instructions (review E-R1).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .rules import DATA_BEGIN, DATA_END

LIST_LIMIT = 10
# Above this the brief still works, but most models start to drop the middle of what they read. A warning,
# not a refusal: refusing would leave the person with no brief at all.
PAYLOAD_WARN_BYTES = 200_000
# A trimmed list `x` gets a sibling key `x_omitted_count`; a trimmed list inside another list ends with one
# `{"omitted_count": n}` item. The prompts name this suffix, so it is one constant.
OMITTED_SUFFIX = "omitted_count"
# The report keys whose entries are checks. Everything else in the payload is left as it is.
CHECK_LISTS = ("gates", "checks", "answer_engine_panel")

log = logging.getLogger(__name__)


def _neutralise(text: str, counter: list[int]) -> str:
    """The marker text, quoted from a site, can no longer open or close the data block."""
    for marker in (DATA_BEGIN, DATA_END):
        if marker in text:
            counter[0] += text.count(marker)
            text = text.replace(marker, marker.replace("<<<", "[site text: ").replace(">>>", "]"))
    return text


def _trim(value: Any, stats: dict[str, int], counter: list[int]) -> Any:
    """A copy of `value` with every list cut to LIST_LIMIT items and every string's markers neutralised."""
    if isinstance(value, str):
        return _neutralise(value, counter)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key = _neutralise(key, counter) if isinstance(key, str) else key
            if isinstance(item, list) and len(item) > LIST_LIMIT:
                out[key] = [_trim(element, stats, counter) for element in item[:LIST_LIMIT]]
                out[f"{key}_{OMITTED_SUFFIX}"] = len(item) - LIST_LIMIT
                stats["lists_trimmed"] += 1
                stats["items_omitted"] += len(item) - LIST_LIMIT
            else:
                out[key] = _trim(item, stats, counter)
        return out
    if isinstance(value, list):
        if len(value) > LIST_LIMIT:
            stats["lists_trimmed"] += 1
            stats["items_omitted"] += len(value) - LIST_LIMIT
            return [_trim(element, stats, counter) for element in value[:LIST_LIMIT]] + \
                [{OMITTED_SUFFIX: len(value) - LIST_LIMIT}]
        return [_trim(element, stats, counter) for element in value]
    return value


def _trim_check(check: dict[str, Any], rank: dict[str, int], stats: dict[str, int],
                counter: list[int]) -> dict[str, Any]:
    """One check with its findings cut worst-first, and every list inside it cut to its first items."""
    findings = check.get("findings")
    if not (isinstance(findings, list) and len(findings) > LIST_LIMIT):
        return _trim(check, stats, counter)
    worst_first = sorted(range(len(findings)),
                         key=lambda i: (rank.get((findings[i] or {}).get("id") if isinstance(findings[i], dict)
                                                 else None, len(rank)), i))
    kept, dropped = sorted(worst_first[:LIST_LIMIT]), worst_first[LIST_LIMIT:]
    rest = _trim({key: item for key, item in check.items() if key != "findings"}, stats, counter)
    stats["lists_trimmed"] += 1
    stats["items_omitted"] += len(dropped)
    return {
        **rest,
        "findings": [_trim(findings[i], stats, counter) for i in kept],
        f"findings_{OMITTED_SUFFIX}": len(dropped),
        # Short ids, kept whole: a model may cite a finding it was not shown, and the checker can still tell a
        # real id from an invented one.
        "findings_omitted_ids": [findings[i]["id"] for i in dropped
                                 if isinstance(findings[i], dict) and findings[i].get("id")],
    }


def payload_size(payload: dict[str, Any]) -> int:
    """Bytes of the payload as JSON in UTF-8, the way it is written into a brief."""
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def budgeted_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """`payload` (from `report.analysis_payload`) with its check lists bounded and its marker text neutralised.

    The result carries `payload_budget`: the size before and after, how many lists were cut and how many items
    they lost, and a warning when the result is still over PAYLOAD_WARN_BYTES. It travels inside the payload so
    a brief in either mode (pointer or inline) states it, and a reader never has to guess whether a list is whole.
    """
    stats = {"lists_trimmed": 0, "items_omitted": 0}
    counter = [0]
    rank = {fid: i for i, fid in enumerate(payload.get("findings_in_priority_order") or []) if isinstance(fid, str)}
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in CHECK_LISTS and isinstance(value, list):
            out[key] = [_trim_check(entry, rank, stats, counter) if isinstance(entry, dict)
                        else _trim(entry, stats, counter) for entry in value]
        else:
            # Outside the checks nothing is cut, but page text can still sit there (the brand name, for one).
            out[key] = _neutralise_all(value, counter)
    budget: dict[str, Any] = {
        "list_limit": LIST_LIMIT,
        "payload_bytes_before": payload_size(payload),
        "lists_trimmed": stats["lists_trimmed"],
        "items_omitted": stats["items_omitted"],
        "markers_neutralised": counter[0],
        "warn_above_bytes": PAYLOAD_WARN_BYTES,
        "note": (f"Inside each check, lists keep their first {LIST_LIMIT} items; a key ending in "
                 f"`{OMITTED_SUFFIX}` says how many were left out. Left out is not absent: the full lists are in "
                 "report.json."),
    }
    out["payload_budget"] = budget
    # Measured last, with the budget block in it, so the number is the size of what is actually handed over.
    budget["payload_bytes"] = payload_size(out)
    if budget["payload_bytes"] > PAYLOAD_WARN_BYTES:
        budget["warning"] = (f"payload is {budget['payload_bytes']} bytes, above {PAYLOAD_WARN_BYTES}; a model may "
                             "not read all of it. Prefer one skill at a time, or a model with a larger context.")
        log.warning("LLM brief payload is %d bytes (limit %d)", budget["payload_bytes"], PAYLOAD_WARN_BYTES)
        budget["payload_bytes"] = payload_size(out)
    return out


def _neutralise_all(value: Any, counter: list[int]) -> Any:
    """Marker neutralising with no list cut, for the parts of the payload outside the checks."""
    if isinstance(value, str):
        return _neutralise(value, counter)
    if isinstance(value, dict):
        return {(_neutralise(k, counter) if isinstance(k, str) else k): _neutralise_all(v, counter)
                for k, v in value.items()}
    if isinstance(value, list):
        return [_neutralise_all(item, counter) for item in value]
    return value
