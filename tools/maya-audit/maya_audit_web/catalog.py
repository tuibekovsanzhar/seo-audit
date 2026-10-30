"""Plain-language notes for every kind of finding, in one place. Every layer reads them from here.

These notes explain. They never measure: the severity, the confidence, the affected pages and the fix all come
from the report. `owner` and `effort` are advice about who usually does this kind of work and roughly how big
it tends to be. They are estimates, are labelled as estimates wherever they are shown, and are not part of the
audit's evidence.

`why` says how the subject of the finding can matter for search and answer engines. It is worded as "can" on
purpose: nothing here promises a better ranking or more citations.

A check that reports several kinds of thing has one note per kind (`_BY_TITLE`), chosen by the finding's title.
`tests/test_web_app.py` reads the engine's own finding titles and fails when one has no note of its own, or when
a note here matches no finding the engine can produce. (An earlier version had one note per check, and showed
the certificate text under a redirect finding and the alt-text note under an image-format one.)
"""

from __future__ import annotations

import json
import re

from . import strings

from maya_audit.recommendation_catalog import _NOTES, _BY_TITLE, _DEFAULT, note as _note

OWNERS = ("developer", "content", "seo")
EFFORTS = ("S", "M", "L")

# For a check that reports one kind of thing: check_id -> (owner, effort, why)

# For a check that reports several kinds of thing. Tried in order against the finding's title; exactly one must match.
# check_id -> ((pattern, owner, effort, why), ...)


def _translations() -> dict[str, dict[str, str]]:
    """The notes in other languages: locales/catalog/<language>.json, each English note mapped to its translation."""
    out: dict[str, dict[str, str]] = {}
    folder = strings.LOCALES / "catalog"
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            table = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(table, dict):
            out[path.stem] = {key: value for key, value in table.items() if isinstance(value, str)}
    return out


def note(check_id: str, title: str = "") -> dict[str, str]:
    """`_note` in the language of the request: the same owner and effort, and `why` translated when a translation exists."""
    found = _note(check_id, title)
    found["why"] = TRANSLATIONS.get(strings.current_language(), {}).get(found["why"], found["why"])
    return found


# Notes kept for reports saved by an earlier engine: nothing in today's source writes a title they match. A title two
# pages share was IDX-8's finding as well as STR-1's until team-preview-13 (decision 187).
SAVED_ONLY = frozenset({("IDX-8", r"share the title"), ("IDX-6", r"point to another site \([^)]*\) at a path that exists on this one$"),
                        ("IDX-5", r"non-200 or noindex"), ("IDX-5", r"written wrongly"),
                        # An STR-10 observation since review G13 (gx2); kept for reports saved before.
                        ("STR-10", r"Open Graph tags but no Twitter card")})


def all_whys() -> list[str]:
    return list(dict.fromkeys([row[2] for row in _NOTES.values()] + [row[-1] for rows in _BY_TITLE.values() for row in rows] + [_DEFAULT[2]]))




def matches(check_id: str, title: str) -> list[str]:
    """The patterns of this check's notes that match `title` (for the catalog test: exactly one, unless a catch-all)."""
    return [pattern for pattern, *_ in _BY_TITLE.get(check_id, ()) if re.search(pattern, title, re.IGNORECASE)]


def has_own_note(check_id: str, title: str) -> bool:
    return check_id in _NOTES or bool(matches(check_id, title))


def known() -> frozenset[str]:
    return frozenset(_NOTES) | frozenset(_BY_TITLE)


TRANSLATIONS = _translations()
