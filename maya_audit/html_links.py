from __future__ import annotations

import codecs
import re
from html.parser import HTMLParser

from .own_document import strip_embedded
from .urls import normalize_url

_SKIP_PREFIXES = ("javascript:", "mailto:", "tel:", "data:", "#")
# Elements that never hold another: they are not "around" a link.
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
BLOCK_NAME_MAX = 80


def block_name(tag: str, attr: dict[str, str | None]) -> str | None:
    """How an element is named when it has a class or an id: "div.post-related", "section#related". The first class
    that holds no digit (else such an id): "post-4711" is one post, not the block every page carries."""
    for mark, value in ((".", attr.get("class")), ("#", attr.get("id"))):
        for token in (value or "").split():
            if not any(ch.isdigit() for ch in token):
                return f"{tag}{mark}{token}"[:BLOCK_NAME_MAX]
    return None


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.base: str | None = None
        self.hrefs: list[str] = []
        self.aria_names = []
        self.label_refs = []
        self.anchors: list[list[str]] = []
        # What stands in for text when a link has none: the alt of an image inside it, then its aria-label or title.
        self.fallbacks: list[list[str]] = []
        self.in_nav: list[bool] = []
        # Each link's address exactly as the page wrote it (fragment included), and the region it sits in
        # ("header", "nav", "footer" or None): what names a shared element (maya_audit.shared_elements).
        self.written: list[str] = []
        self.where: list[str | None] = []
        # Whether each link sits inside a <footer> (whatever is nested in it), and the nearest element around it that
        # has a class or an id ("div.post-related"): what a repeated block is called when it is no header or footer.
        self.in_footer: list[bool] = []
        self.block: list[str | None] = []
        self._blocks: list[tuple[str, str | None]] = []
        self._regions: list[list] = []
        self._open: list[str] | None = None
        self._open_fallback: list[str] | None = None
        # Open navigation containers: [tag, how many of that tag are open inside it].
        self._nav: list[list] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag in ("nav", "header") or (attr.get("role") or "").strip().lower() in ("navigation", "menubar"):
            self._nav.append([tag, 1])
        elif self._nav and tag == self._nav[-1][0]:
            self._nav[-1][1] += 1
        if tag in ("header", "nav", "footer"):
            self._regions.append([tag, 1])
        elif self._regions and tag == self._regions[-1][0]:
            self._regions[-1][1] += 1
        if tag == "base" and attr.get("href") and self.base is None:
            self.base = attr["href"]
        elif tag == "a" and attr.get("href"):
            href = attr["href"].strip()
            if href and not href.lower().startswith(_SKIP_PREFIXES):
                self.hrefs.append(href)
                self.aria_names.append((attr.get("aria-label") or "").strip())
                self.label_refs.append((attr.get("aria-labelledby") or "").split())
                self.in_nav.append(bool(self._nav))
                self.written.append(href)
                self.where.append(self._regions[-1][0] if self._regions else None)
                self.in_footer.append(any(region[0] == "footer" for region in self._regions))
                self.block.append(next((name for _tag, name in reversed(self._blocks) if name), None))
                self._open = []
                self.anchors.append(self._open)
                self._open_fallback = []
                self.fallbacks.append(self._open_fallback)
                self._late = [attr.get("aria-label") or "", attr.get("title") or ""]
            else:
                self._open = self._open_fallback = None
        elif tag in ("img", "svg") and self._open_fallback is not None:
            self._open_fallback.append(attr.get("alt") or attr.get("aria-label") or attr.get("title") or "")
        if tag not in _VOID and len(self._blocks) < 400:
            self._blocks.append((tag, block_name(tag, attr)))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        for at in range(len(self._blocks) - 1, -1, -1):
            if self._blocks[at][0] == tag:
                del self._blocks[at:]
                break
        if self._nav and tag == self._nav[-1][0]:
            self._nav[-1][1] -= 1
            if self._nav[-1][1] <= 0:
                self._nav.pop()
        if self._regions and tag == self._regions[-1][0]:
            self._regions[-1][1] -= 1
            if self._regions[-1][1] <= 0:
                self._regions.pop()
        if tag == "a":
            if self._open_fallback is not None:
                self._open_fallback.extend(self._late)  # the link's own aria-label and title come after an image's alt
            self._open = self._open_fallback = None

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self._open.append(data)


def _clean(parts: list[str]) -> str:
    return " ".join("".join(parts).split())[:200]


def extract_link_edges(html: str, page_url: str, max_anchors: int = 20) -> list[dict]:
    """Link targets in document order, one entry per target, with every anchor text used for it.

    `anchor` is the first non-empty anchor text (kept for the checks that quote one), `anchors` every distinct
    one in document order (the first `max_anchors`), `links` how many links on the page go to the target, and
    `empty` how many of those have no name at all: no text, no image alt, no aria-label, no title. A link
    whose only name is an image's alt or an aria-label counts under that name and is not empty.

    An entry carries `"nav": True` when any link to that target sits in the page's navigation
    (`<nav>`, `<header>`, or an element with role="navigation" or "menubar").

    An entry with a link that has no name also carries `hrefs`: the addresses of those links exactly as the page
    wrote them, fragment included (the first 3 distinct), and `where`: the region the first of them sits in
    ("header", "nav", "footer", or None). `target` drops the fragment, which is what tells one such link from another.
    It also carries `block` when the first of them has an element around it with a class or an id
    ("div.post-related", `block_name`).

    An entry carries `"footer": True` when any link to that target sits inside a `<footer>`.
    """
    parser = _LinkParser()
    html = strip_embedded(html)[0]  # links inside an embedded document are not the page's (maya_audit.own_document)
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # malformed markup: keep whatever was parsed
        pass
    base = normalize_url(parser.base, page_url) if parser.base else page_url
    resolved = {}
    if any(parser.label_refs):
        from .element_context import Tree
        tree = Tree()
        try:
            tree.feed(html); tree.close()
            if tree.complete:
                labels = {n.attrs['id']:n.text() for n in tree.root.descendants() if n.attrs.get('id')}
                resolved = {i:' '.join(labels[r] for r in refs).strip() for i,refs in enumerate(parser.label_refs) if refs and all(r in labels for r in refs)}
        except (ValueError, RecursionError):
            pass
    edges: dict[str, dict] = {}
    for link_index, (href, anchor, fallback, in_nav, where, in_footer, block) in enumerate(zip(parser.hrefs, parser.anchors, parser.fallbacks, parser.in_nav,
                                                                         parser.where, parser.in_footer, parser.block)):
        url = normalize_url(href, base or page_url)
        if not url:
            continue
        name = resolved.get(link_index) or parser.aria_names[link_index] or _clean(anchor) or next((text for text in (_clean([part]) for part in fallback) if text), "")
        edge = edges.setdefault(url, {"target": url, "anchor": "", "anchors": [], "links": 0, "empty": 0})
        edge["links"] += 1
        if name != _clean(anchor) and (resolved.get(link_index) or parser.aria_names[link_index]):
            edge.setdefault("programmatic_names", []).append({"visible": _clean(anchor), "accessible_name": name, "source": "aria-labelledby" if resolved.get(link_index) else "aria-label"})
        counts = edge.setdefault('anchor_counts', {})
        counts[name] = counts.get(name, 0) + 1
        if not name:
            edge["empty"] += 1
            written = edge.setdefault("hrefs", [])
            if href not in written and len(written) < 3:
                written.append(href[:300])
            if "where" not in edge:
                edge["where"] = where
                if block:
                    edge["block"] = block
        elif name not in edge["anchors"] and len(edge["anchors"]) < max_anchors:
            edge["anchors"].append(name)
        if not edge["anchor"]:
            edge["anchor"] = name
        if in_nav:
            edge["nav"] = True
        if in_footer:
            edge["footer"] = True
    return list(edges.values())


def extract_links(html: str, page_url: str) -> list[str]:
    """Absolute, normalized http(s) link targets in document order, deduplicated."""
    parser = _LinkParser()
    html = strip_embedded(html)[0]  # links inside an embedded document are not the page's (maya_audit.own_document)
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # malformed markup: keep whatever was parsed
        pass
    base = normalize_url(parser.base, page_url) if parser.base else page_url
    seen: dict[str, None] = {}
    for href in parser.hrefs:
        url = normalize_url(href, base or page_url)
        if url:
            seen.setdefault(url, None)
    return list(seen)


def is_html(content_type: str | None) -> bool:
    if not content_type:
        return False
    media = content_type.split(";", 1)[0].strip().lower()
    return media in ("text/html", "application/xhtml+xml")


# The labels a browser reads as Windows-1254 (Turkish) and as Windows-1252, as the WHATWG Encoding standard lists
# them: a page that says ISO-8859-1 or US-ASCII is read as Windows-1252 by every browser (DECISIONS 230).
_CP1254 = frozenset({"windows-1254", "iso-8859-9", "latin5", "x-cp1254", "cp1254", "iso8859-9", "iso_8859-9", "iso88599",
                     "iso_8859-9:1989", "iso-ir-148", "l5", "csisolatin5"})
_CP1252 = frozenset({"iso-8859-1", "us-ascii", "ascii", "latin1", "l1", "iso8859-1", "iso_8859-1", "iso88591", "iso_8859-1:1987",
                     "iso-ir-100", "cp819", "ibm819", "csisolatin1", "ansi_x3.4-1968", "windows-1252", "cp1252", "x-cp1252"})
_BOMS = ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"))
# Where a browser looks for a <meta charset> before it starts to read the page (the HTML standard's prescan: 1,024
# bytes; this reads 4,096, as the spec of DECISIONS 230 says, so a long <head> of comments still has it read).
META_PRESCAN_BYTES = 4096
_META_CHARSET = re.compile(rb"<meta\b[^>]*?charset\s*=\s*[\"']?\s*([A-Za-z0-9_.:-]+)", re.IGNORECASE)


def _codec(label: str | None) -> str | None:
    """The Python codec for an encoding label, or None for a label no browser or Python knows."""
    label = (label or "").strip().strip("\"'").strip().lower()
    if not label:
        return None
    if label in _CP1254:
        return "cp1254"
    if label in _CP1252:
        return "cp1252"
    try:
        info = codecs.lookup(label)
    except LookupError:
        return None
    return info.name if getattr(info, "_is_text_encoding", True) else None  # "rot13" and "base64" are no page encodings


def detect_charset(body: bytes, content_type: str | None) -> str:
    """The codec a browser would read `body` with: a byte-order mark first, then the charset of the HTTP Content-Type
    header, then a <meta charset> or <meta http-equiv="Content-Type"> in the first 4,096 bytes, else UTF-8. A label
    that names no known encoding is passed over, as a browser does (DECISIONS 230)."""
    for mark, codec in _BOMS:
        if body.startswith(mark):
            return codec
    if content_type and "charset=" in content_type.lower():
        found = _codec(content_type.lower().split("charset=", 1)[1].split(";", 1)[0])
        if found:
            return found
    match = _META_CHARSET.search(body[:META_PRESCAN_BYTES])
    found = _codec(match.group(1).decode("ascii", "replace")) if match else None
    return found or "utf-8"


def decode_body(body: bytes, content_type: str | None) -> str:
    """`body` as text, read with the encoding `detect_charset` finds; a byte that does not fit becomes U+FFFD."""
    return body.decode(detect_charset(body, content_type), errors="replace")
