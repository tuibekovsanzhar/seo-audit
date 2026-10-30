"""One element, many pages: a problem that the same header or footer element causes is reported once (DECISIONS 171).

A heart icon in the header that links to the favourites page with no text is one thing to fix. Reported per page it
is "1 link has no text at all" on every page of the site: fifty rows that say the same thing and hide the rows that
are about a page. The owner's rule (2026-10-11): when the same element causes a problem on most pages, report it once
for the whole site, name the element so it can be found (the link's href, the image's src, the heading's text), and
take it out of the per-page rows.

"The same element on most pages" is the bar the audit already uses for a text block that most pages share
(`main_content.appears_on_most`, `config.SITEWIDE_SHARE`): on at least 60% of the pages checked and on at least 3 of
them. Nothing is split on a site of fewer than 5 pages: there a page's own row is the clearer report. The bar is an
agent default and is not calibrated (docs/LAUNCH-GATE.md).

An element is known by a key the check chooses:
- a link: its href as written, fragment included, made absolute (`link_key`). The fragment is what tells
  /Hesabim.aspx#/Favorilerim from /Hesabim.aspx#/Siparislerim; the crawler's own address for both drops it;
- a link without an address: its text and why it leads nowhere;
- an image: its src;
- a heading: its level and its text.

A site in several languages has a menu and a footer per language: the Turkish menu is on every Turkish page and on
no English one, so it is on half of the site and on all of its own part. An element is therefore also shared when
most pages of one section carry it (a section is the first part of the path: /tr/, /en/, /blog/; at least 5 pages).

Three more shapes of the same thing (Owner, 2026-10-12):
- links without an address that sit on exactly the same pages (the seven entries of one menu) are one finding that
  lists them, not seven;
- a link with only generic text ("tıklayınız") to the same address on most pages is one element, known by its address
  and its text;
- a link with no text whose address differs on every page but follows one pattern (each product page linking to its
  own photo under /wp-content/uploads/…/*.png) is one template element, known by the pattern and one example.

A check calls `split` with the keys each page has, takes the shared keys out of its per-page finding, and writes one
site-wide finding for each (`finding`). The site-wide finding keeps the severity, confidence, expected result, fix and
notes of the per-page finding it was split from.

What the finding calls the element, and how far it reaches (DECISIONS 198, which amends 171 and 183):
- "Shared header/footer" only when the markup puts the element in a header, a navigation or a footer. An element in
  a block the markup names (the nearest element around it with a class or an id) is "“div.post-related” block"; any
  other is "Repeated block" (`label`);
- an element shared only by the pages of one section (a related-posts block under /blog/) is not a whole-site
  problem: `split` says which keys those are (`Shared.sections`), and their finding has an ordinary page scope and says
  "on 6 page(s) of /blog/". It is still one element and one line: "Problems by page" lists it once, beside the
  whole-site problems, and not on each page's row (`report.grouped_once`);
- nameless links that sit in one named block on the same pages are one finding that counts them (`BLOCK_LINKS_TITLE`).
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit

from .findings import Finding, scope_for
from .main_content import appears_on_most

# Fewer pages than this and nothing is split: every problem stays on its page's own row.
MIN_PAGES = 5
LABEL = "Shared header/footer"
# The site-wide finding's title, by kind. Each names the element. (English display forms and translations:
# maya_audit_web.wording, keys `shared.*`.)
TITLES = {
    "link_no_text": "Shared header/footer: link to {href} has no text (on {pages} page(s))",
    "link_no_address": "Shared header/footer: link “{text}” has no address (on {pages} page(s))",
    "heading_jump": "Shared header/footer: heading “{text}” (H{to}) comes after an H{before}, skipping a level (on {pages} page(s))",
    "heading_jump_varied": "Shared header/footer: heading “{text}” (H{to}) comes after a higher-level heading, skipping levels (on {pages} page(s))",
    "image_no_alt": "Shared header/footer: image {src} has no alt text (on {pages} page(s))",
    "links_no_address": "Shared header/footer: {links} links have no address ({texts}) (on {pages} page(s))",
    "link_generic": "Shared header/footer: link “{text}” to {href} has only generic text (on {pages} page(s))",
    "link_no_text_pattern": "Shared template: links to {pattern} have no text (on {pages} page(s)), for example {href}",
}
# Nameless links in one block the markup names, on the same pages: one finding (its kind stays `link_no_text`).
BLOCK_LINKS_TITLE = "“{block}” block: {links} link(s) have no text (on {pages} page(s))"
BLOCK_LABEL = "“{block}” block"
REPEATED_LABEL = "Repeated block"
# The regions whose elements are called "Shared header/footer".
CHROME_REGIONS = ("header", "nav", "footer")
# How many link texts a grouped finding's title names before "and N more".
TEXTS_NAMED = 4
# Where on the page a shared element sits: one of the page's own regions, or "repeated" (most pages carry it, and the
# markup does not say which region it belongs to).
REGIONS = ("header", "nav", "footer", "aside")
REPEATED = "repeated"
DATA_ADDRESS_SHOWN = 60


def section_of(url: str) -> str:
    """The part of the site a page is in: the first part of its path ("tr" for /tr/hakkimizda/), "" at the top."""
    parts = [part for part in urlsplit(url).path.split("/") if part]
    return parts[0].lower() if len(parts) > 1 or (parts and urlsplit(url).path.endswith("/")) else ""


class Shared(set):
    """The shared keys. `sections` holds the keys that are shared by section only (not by most of the site), each with
    the sections whose pages mostly carry it: {key: ["blog"]}."""

    def __init__(self, keys: Iterable = (), sections: dict[Any, list[str]] | None = None) -> None:
        super().__init__(keys)
        self.sections: dict[Any, list[str]] = sections or {}

    def section(self, key: Any, urls: Iterable[str]) -> str | None:
        """The one section a key is shared in, when it is shared by section only and every page that carries it is in
        that section; "" when it is shared by section only in any other way; None when most of the site carries it."""
        named = self.sections.get(key)
        if named is None:
            return None
        return named[0] if len(named) == 1 and all(section_of(url) == named[0] for url in urls) else ""


def split(keys_by_page: dict[str, Iterable], pages_checked: int | Iterable[str] | None = None) -> Shared:
    """The keys that most of the pages checked carry: the same bar as a shared text block. `keys_by_page` holds the
    keys of each page that has any; `pages_checked` is how many pages the check looked at, or their addresses (pages
    with no key count against the share). With the addresses, a key that most pages of one section carry is shared
    too (a menu per language). Empty when fewer than `MIN_PAGES` pages were checked.

    The set that comes back also says which keys are shared by section only (`Shared.sections`): their finding is
    about that section's pages, not the whole site."""
    urls = None if pages_checked is None or isinstance(pages_checked, int) else list(dict.fromkeys(pages_checked))
    total = max(len(urls) if urls is not None else (pages_checked or 0), len(keys_by_page))
    if total < MIN_PAGES:
        return Shared()
    per_page = [set(keys) for keys in keys_by_page.values()]
    shared = Shared(appears_on_most(per_page + [set()] * (total - len(per_page))))
    sections: dict[str, list[str]] = {}
    for url in urls or []:
        sections.setdefault(section_of(url), []).append(url)
    for section, pages in sections.items():
        if section and len(pages) >= MIN_PAGES:
            for key in appears_on_most([set(keys_by_page.get(url) or ()) for url in pages]) - set(shared):
                shared.sections.setdefault(key, []).append(section)
    shared |= set(shared.sections)
    return shared


def address_pattern(address: str, origin: str | None = None) -> str | None:
    """The pattern a file's address follows, for links that differ on every page and come from one template:
    "/wp-content/uploads/…/*.png". None for an address that is a page (pages are told apart, never grouped)."""
    from .urls import non_page_kind

    parts = urlsplit(address)
    if non_page_kind(address) not in ("image", "document") or "." not in parts.path.rsplit("/", 1)[-1]:
        return None
    folders = [part for part in parts.path.split("/")[:-1] if part]
    ending = parts.path.rsplit(".", 1)[-1].lower()
    host = "" if origin and (parts.scheme, parts.netloc) == (urlsplit(origin).scheme, urlsplit(origin).netloc) else f"{parts.scheme}://{parts.netloc}"
    return f"{host}/" + "/".join(folders[:2]) + ("/…" if len(folders) > 2 else "") + f"/*.{ending}"


def named(texts: Iterable[str]) -> str:
    """The first few link texts, quoted, and how many more there are: “A”, “B”, “C”, “D” and 3 more."""
    texts = list(texts)
    shown = ", ".join(f"“{text}”" for text in texts[:TEXTS_NAMED])
    return shown + (f" and {len(texts) - TEXTS_NAMED} more" if len(texts) > TEXTS_NAMED else "")


def link_key(href: str, page_url: str) -> str:
    """A link's address as the page wrote it, made absolute, with its fragment kept."""
    return urljoin(page_url, (href or "").strip())


def shown_address(address: str, origin: str | None) -> str:
    """An address as a report names it: a path when it is on the audited site ("/Hesabim.aspx#/Favorilerim"), whole
    otherwise. A `data:` address is cut (`short_data_address`)."""
    address = short_data_address(address or "")
    if not origin:
        return address
    there, here = urlsplit(address), urlsplit(origin)
    if there.scheme not in ("http", "https") or (there.scheme, there.netloc) != (here.scheme, here.netloc):
        return address
    return (there.path or "/") + (f"?{there.query}" if there.query else "") + (f"#{there.fragment}" if there.fragment else "")


def short_data_address(address: str) -> str:
    """An image written into the page as a `data:` address can be hundreds of kilobytes long. It is stored and shown
    as its first 60 characters and its size: "data:image/png;base64,iVBORw0KGgo… (512 KB data address)"."""
    if not address.startswith("data:") or len(address) <= DATA_ADDRESS_SHOWN + 40:
        return address
    return f"{address[:DATA_ADDRESS_SHOWN]}… ({max(1, round(len(address) / 1024))} KB data address)"


def region(found: Iterable[str | None]) -> str:
    """The region most of an element's occurrences sit in, or "repeated" when the markup names none."""
    named = Counter(where for where in found if where in REGIONS)
    return named.most_common(1)[0][0] if named else REPEATED


def block(found: Iterable[str | None]) -> str | None:
    """The block most of an element's occurrences sit in ("div.post-related"), or None when the markup names none."""
    named = Counter(name for name in found if name)
    return named.most_common(1)[0][0] if named else None


def label(where: str | None, block: str | None = None) -> str:
    """What a shared element is called in its finding's title: "Shared header/footer" only when the markup puts it in a
    header, a navigation or a footer; the block's own name when it has one; "Repeated block" otherwise."""
    if where in CHROME_REGIONS:
        return LABEL
    return BLOCK_LABEL.format(block=block) if block else REPEATED_LABEL


def finding(like: Finding, kind: str, element: dict[str, Any], urls: list[str], evidence: dict[str, Any] | None = None,
            importance_tier: int | None = None, section: str | None = None, title: str | None = None, **title_values: Any) -> Finding:
    """One finding for one shared element. `like` is a finding of the kind it was split from: its check, severity,
    confidence, rationale, engines, expected result, fix, notes and importance are kept. `element` says what the
    element is (`type`, then `href`, `src` or `text`, `where`, and `block` when the markup names one); `urls` are the
    pages that carry it.

    `section` is what `Shared.section` said of the element's key: None for an element most of the site carries (a
    site-wide finding); a section's name or "" for one shared by section only (a finding about those pages, with
    "of /blog/" after the page count when they are all in one section). `title` is a title template to use in place
    of the kind's (`BLOCK_LINKS_TITLE`)."""
    urls = sorted(set(urls))
    # `section` is in the element exactly when it is shared by section only ("" when no one section holds all its pages).
    shared = {**element, "kind": kind, "pages": len(urls), **({"section": section} if section is not None else {})}
    said = (title or TITLES[kind]).format(pages=len(urls), **title_values)
    called = label(element.get("where"), element.get("block"))
    if called != LABEL and said.startswith(LABEL + ": "):
        said = called + said[len(LABEL):]
    if section:
        said = said.replace(f"(on {len(urls)} page(s))", f"(on {len(urls)} page(s) of /{section}/)")
    return Finding(like.check_id, said, like.severity, like.confidence, like.rationale,
                   list(like.engines), scope_for(urls, sitewide=section is None), {"shared_element": shared, **(evidence or {})},
                   like.expected, like.how_to_fix, notes=list(like.notes),
                   importance_tier=like.importance_tier if importance_tier is None else importance_tier)
