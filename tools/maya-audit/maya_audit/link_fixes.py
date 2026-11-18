"""DECISIONS 360 (İlginay's review of the MMI Ek): a link card's own step on each page names the links it means: the link
text (or "(metin yok)"), the address the page writes, where the link sits and, for a link to an alias, the address to
write instead. Built from the rule's evidence and the page's recorded links, for a new report and a saved one alike.
Each fix is {"url": page, "fix": {"tr", "en"}}, read by `page_rows.row_fix` as the row's "Ne yapılmalı"."""
from __future__ import annotations

from urllib.parse import urlsplit

PLACE = {"tr": {"menu": "menü", "footer": "alt bilgi", "body": "gövde", "header": "üst bilgi"},
         "en": {"menu": "menu", "footer": "footer", "body": "body", "header": "header"}}
NO_TEXT = {"tr": "(metin yok)", "en": "(no text)"}
SHOWN = 3  # links named in one row's step


def path(url: str | None) -> str:
    parts = urlsplit(url or "")
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def place_of(edge: dict | None) -> str:
    """menu, footer or body for a recorded link (its `nav`/`footer` flags, or the `where` a rule wrote)."""
    e = edge or {}
    where = str(e.get("where") or "").lower()
    if e.get("nav") or e.get("in_navigation") or where in ("nav", "menu", "header"):
        return "menu"
    if e.get("footer") or where == "footer":
        return "footer"
    return "body"


def describe(text: str | None, href: str | None, place: str, lang: str, block: str | None = None) -> str:
    shown = f"«{text}»" if text else NO_TEXT[lang]
    where = PLACE[lang][place] + (f", {block}" if block else "")
    return f"{shown} → {path(href)} ({where})"


def no_text_fixes(rows: list[dict]) -> list[dict]:
    """The nameless links of each page (STR-14's `links` rows: source, target, hrefs, where/in_navigation, block)."""
    by_page: dict[str, list[dict]] = {}
    for r in rows or []:
        if isinstance(r, dict) and r.get("source"):
            by_page.setdefault(r["source"], []).append(r)
    out = []
    for page, links in by_page.items():
        parts = {lang: "; ".join(describe(None, (r.get("hrefs") or [r.get("target")])[0], place_of(r), lang, r.get("block"))
                                 for r in links[:SHOWN]) for lang in ("tr", "en")}
        out.append({"url": page, "fix": {"tr": f"Bu bağlantılara görünür metin ya da aria-label verin: {parts['tr']}.",
                                         "en": f"Give these links visible text or an aria-label: {parts['en']}."}})
    return out


def alias_fixes(pages, aliases: dict[str, str]) -> list[dict]:
    """Each page's links to an address whose canonical is another page, with the canonical to link to instead. `pages`
    are page records (objects or saved dicts) with their recorded `outlinks`."""
    out = []
    for p in pages:
        url = p.get("url") if isinstance(p, dict) else getattr(p, "url", None)
        outlinks = (p.get("outlinks") if isinstance(p, dict) else getattr(p, "outlinks", None)) or []
        mine, seen = [], set()
        for e in outlinks:
            target = (e.get("target") or "").split("#", 1)[0]
            if target in aliases and target != url and aliases[target] != url and target not in seen:
                seen.add(target)
                mine.append((e, target))
        if not mine:
            continue
        rows = {lang: "; ".join(f"{describe(e.get('anchor'), e.get('href') or t, place_of(e), lang)} ⇒ {path(aliases[t])}"
                                for e, t in mine[:SHOWN]) for lang in ("tr", "en")}
        out.append({"url": url, "fix": {"tr": f"Bağlantıyı kanonik adrese verin: {rows['tr']}.",
                                        "en": f"Link to the canonical address: {rows['en']}."}})
    return out
