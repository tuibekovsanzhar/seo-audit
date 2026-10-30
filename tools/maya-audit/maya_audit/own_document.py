"""The page's own document, with documents embedded in it taken out (DECISIONS 167).

A page reader may hand back a page with the documents of its iframes written into it: the frame becomes
`<div src="https://widget.example/" data-original-tag="iframe">` and the frame's whole document follows inside it,
`<!DOCTYPE html><html><head><meta name="robots" content="noindex"><title>Widget</title>...`. Read as one document,
the widget's robots tag, title, links and text become the page's (seen on 2026-10-11: 50 of 50 pages of a site
reported as noindex because of a chat widget).

The rule: an embedded document is treated like the iframe it came from. Its text, headings, links, images,
structured data, meta tags and title are not the page's. Two shapes are taken out:

1. any element carrying `data-original-tag="iframe"`, with everything inside it;
2. a second `<!DOCTYPE` or `<html>` that starts after the page's body content began, up to its `</html>`. When the
   element it sits in ends before any `</html>`, up to that end; when neither is found, to the end of the file.

One pass over the tags, no backtracking pattern: safe on very large and on broken HTML. A page with neither shape
is returned as it came, after two cheap searches.
"""

from __future__ import annotations

import re
from typing import Any

# What may come before the body: none of these starts the page's content (maya_audit.analysis uses the same set).
BEFORE_BODY = frozenset({"html", "head", "title", "meta", "link", "script", "style", "base", "noscript", "template"})
VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
# Elements whose content is text, not markup: a "<html>" written inside one is not a tag.
RAW_TEXT = frozenset({"script", "style", "textarea", "title"})
MAX_RECORDED = 50

_TOKEN = re.compile(r"<(?:!--|!doctype\b|/?[a-zA-Z][^\s/>]*)", re.I)
_END_OR_QUOTE = re.compile(r"[>\"']")
_MARKED = re.compile(r"data-original-tag\s*=\s*[\"']?iframe\b", re.I)
_MARKER = re.compile(r"data-original-tag", re.I)
_DOCUMENT_START = re.compile(r"<(?:!doctype|html)\b", re.I)
_SRC = re.compile(r"\s(?:data-)?src\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>\"']+))", re.I)
_CLOSERS = {name: re.compile(f"</{name}\\b", re.I) for name in RAW_TEXT}


class _Scan:
    def __init__(self, html: str) -> None:
        self.html, self.size = html, len(html)
        self.no_more = {'"': False, "'": False}  # a quote that never closes is looked for once, not once per tag

    def tag_end(self, at: int) -> int:
        """The index just after the `>` that ends the tag starting before `at`; a `>` inside a quoted value is not it."""
        html = self.html
        while True:
            found = _END_OR_QUOTE.search(html, at)
            if found is None:
                return self.size
            mark = found.group(0)
            if mark == ">":
                return found.end()
            at = found.end()
            before = found.start() - 1
            while before >= 0 and html[before] in " \t\r\n" and found.start() - before < 16:
                before -= 1
            if before < 0 or html[before] != "=" or self.no_more[mark]:
                continue  # a stray quote, not the start of a value
            close = html.find(mark, at)
            if close < 0:
                self.no_more[mark] = True
                continue
            at = close + 1


def embedded_spans(html: str) -> list[tuple[int, int, str | None]]:
    """(start, end, src) of each embedded document in `html`, in order. `src` is the frame's address when the
    reader kept it, else None."""
    if not html or not isinstance(html, str):
        return []
    if _MARKER.search(html) is None and len(_DOCUMENT_START.findall(html)) < 2:
        return []
    scan = _Scan(html)
    size = scan.size
    spans: list[tuple[int, int, str | None]] = []
    stack: list[str] = []
    open_count: dict[str, int] = {}
    seen_document = after_doctype = body_began = False
    # A marked element being skipped: where it starts, its tag, how many of that tag are open, its src.
    wrapper: dict[str, Any] | None = None
    # A second document with no wrapper: where it starts and the element it sits in.
    second: dict[str, Any] | None = None
    at = 0
    while True:
        found = _TOKEN.search(html, at)
        if found is None:
            break
        start, token = found.start(), found.group(0).lower()
        if token == "<!--":
            close = html.find("-->", found.end())
            at = size if close < 0 else close + 3
            continue
        end = scan.tag_end(found.end())
        at = end
        closing = token.startswith("</")
        name = "!doctype" if token == "<!doctype" else token[2:] if closing else token[1:]
        tag_text = html[start:end]
        self_closed = tag_text.endswith("/>")
        if not closing and name in RAW_TEXT and not self_closed:
            closer = _CLOSERS[name].search(html, end)
            at = size if closer is None else closer.start()

        if wrapper is not None:
            if name == wrapper["name"] and not closing and not self_closed:
                wrapper["depth"] += 1
            elif name == "html" and closing:
                # The embedded document is over; whatever it left open inside is not counted against the wrapper.
                wrapper["depth"], wrapper["document_end"] = 1, end
            elif name == wrapper["name"] and closing:
                wrapper["depth"] -= 1
                if wrapper["depth"] <= 0:
                    spans.append((wrapper["start"], end, wrapper["src"]))
                    wrapper = None
            continue
        if second is not None:
            if name == "html" and closing:
                spans.append((second["start"], end, None))
                second = None
            elif second["inside"] and name == second["inside"]:
                second["depth"] += -1 if closing else (0 if self_closed else 1)
                if second["depth"] <= 0:
                    # The element it sits in ended before any </html>: the document ends there. The next </html> is
                    # the page's own, and what lies between is the page's.
                    spans.append((second["start"], start, None))
                    second = None
                    at = start  # the closing tag is read again, as the page's
            continue

        if name == "!doctype":
            if not seen_document:
                seen_document = after_doctype = True
            elif body_began:
                second = {"start": start, "inside": stack[-1] if stack else None, "depth": 1}
            continue
        if closing:
            after_doctype = False
            if open_count.get(name):
                while stack:
                    popped = stack.pop()
                    open_count[popped] -= 1
                    if popped == name:
                        break
            continue
        if name == "html":
            if seen_document and body_began and not after_doctype:
                second = {"start": start, "inside": stack[-1] if stack else None, "depth": 1}
                continue
            seen_document, after_doctype = True, False
        else:
            after_doctype = False
            if name == "body" or name not in BEFORE_BODY:
                body_began = True
        if _MARKED.search(tag_text):
            source = _SRC.search(tag_text)
            src = next((value for value in source.groups() if value), None) if source else None
            if name in VOID or self_closed:
                spans.append((start, end, src))
            else:
                wrapper = {"start": start, "name": name, "depth": 1, "src": src, "document_end": None}
            continue
        if name not in VOID and not self_closed:
            stack.append(name)
            open_count[name] = open_count.get(name, 0) + 1
    if wrapper is not None:  # never closed: to the end of the document inside it, else to the end of the file
        spans.append((wrapper["start"], wrapper["document_end"] or size, wrapper["src"]))
    if second is not None:  # no </html> and the element it sits in never ended: to the end of the file
        spans.append((second["start"], size, None))
    return spans


def without(html: str, spans: list[tuple[int, int, str | None]]) -> str:
    if not spans:
        return html
    kept, at = [], 0
    for start, end, _src in spans:
        kept.append(html[at:start])
        at = end
    kept.append(html[at:])
    return "".join(kept)


def records(spans: list[tuple[int, int, str | None]]) -> list[dict[str, Any]]:
    """What was taken out, as the page's analysis records it: the frame's address and how many characters it was."""
    return [{"src": src, "chars": end - start} for start, end, src in spans[:MAX_RECORDED]]


def strip_embedded(html: str) -> tuple[str, list[dict[str, Any]]]:
    """`html` without the documents embedded in it, and what was taken out: [{"src", "chars"}]."""
    spans = embedded_spans(html)
    return without(html, spans), records(spans)
