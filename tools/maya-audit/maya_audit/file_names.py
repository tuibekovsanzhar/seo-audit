"""Image and file names that break somewhere (DECISIONS 364).

A file uploaded with a name such as "Banner(Espolòn, Día)-01.jpg" keeps that name in its address: brackets and commas
(a comma also separates the candidates of a srcset, and an unquoted CSS url() ends at a bracket), a space that is not
encoded, or an accent written as a letter plus a combining mark (U+0300, U+0301: what macOS file names hold), which makes
a second spelling of the same name and shows as empty boxes in some viewers. The fix is the same for all of them: rename
the file to plain lower-case letters, digits and hyphens before uploading it.

`problems` tests one address as the page writes it; an image proxy (Next.js `/_next/image?url=...`, `?src=`, `?file=`)
is tested on the file address in its parameter. `scan` lists, for a new crawl, the addresses the analyser keeps no other
record of: srcset candidates, CSS backgrounds (style attributes and <style> blocks), file links, og:image and Product
images in the markup. A saved report is tested from what it keeps (img src, og:image, the image sample, the saved
JSON-LD).
"""
from __future__ import annotations

import html as _html
import re
import unicodedata
from urllib.parse import unquote, urljoin, urlsplit

SPACE, COMBINING, PUNCT = "space", "combining", "brackets_commas"
PROBLEMS = (SPACE, COMBINING, PUNCT)
BRACKETS_COMMAS = frozenset("()[]{},")
PROXY_KEYS = ("url", "src", "image", "img", "file", "filename", "u")
DOCUMENT = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?|zip|csv|txt|rtf|odt|ods)$", re.I)
FILE = re.compile(r"\.(?:jpe?g|png|gif|webp|avif|svg|bmp|tiff?|ico|heic|mp4|webm|mov|mp3)$", re.I)
MAX_REFS = 60

_MEDIA_TAG = re.compile(r"<(img|source|video|audio|input)\b([^>]*)>", re.I)
_LINK_TAG = re.compile(r"<a\b([^>]*)>", re.I)
_ATTR = re.compile(r"""\s([a-z-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
_MEDIA_ATTRS = {"src": "img src", "data-src": "img src", "data-lazy-src": "img src", "data-original": "img src",
                "poster": "img src", "srcset": "srcset", "data-srcset": "srcset"}
_STYLE_ATTR = re.compile(r"""\sstyle\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
_STYLE_BLOCK = re.compile(r"<style\b[^>]*>(.*?)</style>", re.I | re.S)
_CSS_URL = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|((?:[^()\s"']|\([^()\s]*\))*))\s*\)""", re.I)


def file_address(ref: str) -> str:
    """The address of the file itself, as written: for an image proxy, the file address in its parameter (decoded once:
    the proxy encodes the address the site wrote). Not split with parse_qsl, which would read a "+" as a space."""
    for part in urlsplit(ref).query.split("&"):
        key, _, value = part.partition("=")
        if key.lower() in PROXY_KEYS and value:
            inner = unquote(value)
            if "/" in inner or FILE.search(inner.split("?")[0]) or DOCUMENT.search(inner.split("?")[0]):
                return inner
    return ref


def file_name(ref: str) -> str:
    """The decoded file name at the end of the file's address."""
    return unquote(urlsplit(file_address(ref)).path).rsplit("/", 1)[-1]


def problems(ref: str) -> list[str]:
    """What is wrong with the file name in `ref` (an address as the page writes it): SPACE (a space not encoded),
    COMBINING (an accent written as a combining mark), PUNCT (brackets or commas in the file name)."""
    ref = (ref or "").strip()
    if not ref or ref.startswith(("data:", "blob:", "#", "javascript:")):
        return []
    path = urlsplit(file_address(ref)).path
    decoded = unquote(path)
    out = []
    if " " in path:
        out.append(SPACE)
    if any(unicodedata.combining(c) for c in decoded):
        out.append(COMBINING)
    if BRACKETS_COMMAS & set(decoded.rsplit("/", 1)[-1]):
        out.append(PUNCT)
    return out


def marks(ref: str) -> list[str]:
    """The combining marks in the file's address, as U+ codes."""
    return sorted({f"U+{ord(c):04X}" for c in unquote(urlsplit(file_address(ref)).path) if unicodedata.combining(c)})


def plain_name(name: str) -> str:
    """`name` as plain lower-case letters, digits and hyphens, the extension kept: "BannerWebsite(Espolòn,Día)-01.jpg" ->
    "banner-website-espolon-dia-01.jpg"."""
    stem, dot, ext = name.rpartition(".")
    if not dot or not ext.isalnum() or len(ext) > 5:
        stem, ext = name, ""
    text = unicodedata.normalize("NFKD", stem.replace("İ", "I").replace("ı", "i"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", "-", text)  # words run together in camel case; an acronym stays whole
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (text or "file") + (f".{ext.lower()}" if ext else "")


def srcset_urls(value: str) -> list[str]:
    """The candidate addresses of a srcset, read as browsers read it: an address runs to the next whitespace, and a
    comma at its end closes the candidate."""
    out, i, n = [], 0, len(value)
    while i < n:
        while i < n and (value[i].isspace() or value[i] == ","):
            i += 1
        j = i
        while j < n and not value[j].isspace():
            j += 1
        url = value[i:j]
        if url.endswith(","):
            url, i = url.rstrip(","), j
        else:
            k = value.find(",", j)
            i = n if k < 0 else k + 1
        if url:
            out.append(url)
    return out


def product_images(values) -> list[str]:
    """The image addresses of the Product nodes in parsed structured data (a string, a list, or ImageObjects)."""
    from .analysis import _product_nodes
    out: list[str] = []

    def add(v):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            add(v.get("contentUrl") or v.get("url"))
        elif isinstance(v, list):
            for x in v[:10]:
                add(x)
    for value in values:
        for node, _ in _product_nodes(value, False, False):
            add(node.get("image"))
    return list(dict.fromkeys(out))


def _attrs(text: str) -> dict[str, str]:
    return {m.group(1).lower(): _html.unescape(m.group(2) if m.group(2) is not None else m.group(3) or "")
            for m in _ATTR.finditer(" " + text)}


def scan(html: str, *, og_images=(), products=()) -> list[dict]:
    """[{url, where, problems}] for the file addresses in `html` (and the page's og:image and Product image values)
    whose file name has a problem, one per file, at most MAX_REFS."""
    found: list[tuple[str, str]] = []
    for m in _MEDIA_TAG.finditer(html):
        for name, value in _attrs(m.group(2)).items():
            where = _MEDIA_ATTRS.get(name)
            if where == "srcset":
                found += [(u, where) for u in srcset_urls(value)]
            elif where:
                found.append((value, where))
    for m in _LINK_TAG.finditer(html):
        href = _attrs(m.group(1)).get("href") or ""
        if DOCUMENT.search(urlsplit(href).path):
            found.append((href, "file link"))
    css = [_html.unescape(a or b or "") for a, b in _STYLE_ATTR.findall(html)] + _STYLE_BLOCK.findall(html)
    for block in css:
        for a, b, c in _CSS_URL.findall(block):
            found.append(((a or b or c).strip(), "css background"))
    found += [(u, "og:image") for u in og_images if isinstance(u, str)]
    found += [(u, "Product image") for u in products if isinstance(u, str)]
    out: dict[str, dict] = {}
    for ref, where in found:
        bad = problems(ref)
        if not bad:
            continue
        key = file_address(ref.strip())
        if key in out:
            if where not in out[key]["where"]:
                out[key]["where"].append(where)
            continue
        if len(out) >= MAX_REFS:
            break
        out[key] = {"url": ref.strip()[:400], "where": [where], "problems": bad}
    return list(out.values())


def absolute(ref: str, page: str) -> str:
    """`ref` as an absolute address against the page (the proxy's own address, not the file in it)."""
    try:
        return urljoin(page, ref.strip())
    except ValueError:
        return ref.strip()
