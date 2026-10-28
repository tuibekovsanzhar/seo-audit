"""A page's own content: its text with the header, navigation, footer and site-wide blocks left out.

Two pages of one site share most of their words before either says anything: the menu, the footer,
a cookie notice, a "from 29 USD" banner. Checks that compare pages with each other, or a page with
its own markup, are misled by that shared text. This module removes it in two steps:

1. structure: text inside <header>, <nav>, <footer> or <aside> is not content, and when the page has
   a <main> or <article>, only text inside it is (`analysis["_content_blocks"]`);
2. repetition: a text block that appears on most of the audited pages is site furniture even when
   the markup does not say so (`repeated_blocks`).

Both are estimates and every check that uses them says so in its evidence.
"""

from __future__ import annotations

import math
from collections import Counter

from .config import SITEWIDE_MIN_PAGES, SITEWIDE_SHARE, TEASER_MIN_PAGES, TEASER_SHARE

BASIS = (f"main content only: text in <header>, <nav>, <footer> and <aside> is left out, and so is any text block that "
         f"appears on at least {SITEWIDE_SHARE:.0%} of the audited pages (when {SITEWIDE_MIN_PAGES} or more were audited)")


def norm(text: str) -> str:
    return " ".join(text.casefold().split())


def content_blocks(analysis: dict) -> list[str]:
    """Text blocks outside the page chrome. Falls back to every block for an analysis made before this existed."""
    blocks = analysis.get("_content_blocks")
    return list(blocks) if blocks is not None else list(analysis.get("_text_blocks") or [])


def appears_on_most(items_per_page: list[set]) -> set:
    """Items present on at least SITEWIDE_SHARE of the pages. Empty when too few pages were audited to tell."""
    pages = len(items_per_page)
    if pages < SITEWIDE_MIN_PAGES:
        return set()
    needed = max(3, math.ceil(SITEWIDE_SHARE * pages))
    counts = Counter(item for items in items_per_page for item in items)
    return {item for item, n in counts.items() if n >= needed}


def repeated_blocks(pages: list) -> set[str]:
    """Normalised text blocks that most of these pages carry (menus and banners not marked up as such)."""
    return appears_on_most([{norm(block) for block in content_blocks(page.analysis)} for page in pages])


def main_blocks(analysis: dict, repeated: set[str]) -> list[str]:
    return [block for block in content_blocks(analysis) if norm(block) not in repeated]


def body_blocks(analysis: dict, repeated: set[str]) -> list[str]:
    """Main-content text that is running text: no headings and no link, button or form labels.

    A page called "Sample pages" or a menu entry "Örnek Sayfalar" is a name, not text somebody forgot to replace.
    """
    blocks, kinds = content_blocks(analysis), analysis.get("_content_block_kinds") or []
    if len(kinds) != len(blocks):
        return main_blocks(analysis, repeated)
    return [block for block, kind in zip(blocks, kinds) if kind == "text" and norm(block) not in repeated]


def heading_blocks(analysis: dict, repeated: set[str]) -> list[str]:
    """The headings of the page's own content (not the footer's column titles, not ones most pages share)."""
    blocks, kinds = content_blocks(analysis), analysis.get("_content_block_kinds") or []
    if len(kinds) != len(blocks):
        return []
    return [block for block, kind in zip(blocks, kinds) if kind == "heading" and norm(block) not in repeated]


def own_text(analysis: dict, repeated_everywhere: set[str]) -> str:
    """Every text block of the page, chrome included, except the blocks most pages share."""
    return " ".join(block for block in analysis.get("_text_blocks") or [] if norm(block) not in repeated_everywhere)


def blocks_on_most_pages(pages: list) -> set[str]:
    """Like `repeated_blocks`, over all of each page's text rather than its content only (a banner lives in the header)."""
    return appears_on_most([{norm(block) for block in page.analysis.get("_text_blocks") or []} for page in pages])


def teaser_blocks(pages: list) -> set[str]:
    """Normalised text blocks that a good part of the site repeats: on at least TEASER_SHARE of the pages and on at
    least TEASER_MIN_PAGES of them. A carousel of blog cards sits on a section of a site, not on most of it, so
    `blocks_on_most_pages` does not see it; a price inside it is still not the price of the page it is shown on."""
    needed = max(TEASER_MIN_PAGES, math.ceil(TEASER_SHARE * len(pages)))
    counts = Counter(block for page in pages for block in {norm(b) for b in page.analysis.get("_text_blocks") or []})
    return {block for block, n in counts.items() if n >= needed}


def main_words(analysis: dict, repeated: set[str]) -> list[str]:
    return " ".join(main_blocks(analysis, repeated)).casefold().split()
