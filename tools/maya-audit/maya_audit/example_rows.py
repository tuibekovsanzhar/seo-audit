"""DECISIONS 368: each page's own line for findings that used to say only a count ("1 bağlantı", "312 → 587 kelime"):
which text, which element, where on the page. A line is written into the finding's evidence record for that page as
`row` ({"tr", "en"}), which "Bulgu bazında" shows as the measured value (`page_rows.measured`), and the Özet's "Örnek"
column takes the first concrete one (`concrete`).

Global for every site: nothing here names a brand, an address or a fixed text; every value comes from the page."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote, urlsplit

LANGUAGES = {"tr": {"en": "İngilizce", "tr": "Türkçe", "de": "Almanca", "fr": "Fransızca", "es": "İspanyolca",
                    "it": "İtalyanca", "pt": "Portekizce", "nl": "Felemenkçe"},
             "en": {"en": "English", "tr": "Turkish", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian",
                    "pt": "Portuguese", "nl": "Dutch"}}
QUOTE_CHARS = 80
# A value that shows a concrete thing: quoted page text, an address, a path or a markup element.
CONCRETE = re.compile(r"«[^»]+»|“[^”]+”|\"[^\"]+\"|https?://\S+|(?<![\w])/[\w\-./%?=&#~+]+|<[a-zA-Z][^<>]{0,40}>")


def quote(text, limit: int = QUOTE_CHARS) -> str:
    """«text», cut to `limit` characters with an ellipsis."""
    text = " ".join(str(text or "").split())
    return "«" + (text if len(text) <= limit else text[:limit - 1].rstrip() + "…") + "»"


def concrete(text) -> bool:
    return isinstance(text, str) and bool(CONCRETE.search(text))


def _lang(code, lang: str) -> str:
    return LANGUAGES[lang].get(code or "", code or "?")


def _more(n: int, lang: str) -> str:
    return (f" (+{n} daha)" if lang == "tr" else f" (+{n} more)") if n > 0 else ""


def row(make) -> dict:
    return {"tr": make("tr"), "en": make("en")}


# ------------------------------------------------------------------------------------------------ STR-12 headings

def headings_language(declared: str, detected: str | None, language: str, headings: list[str]) -> dict:
    def make(lang):
        shown = ", ".join(quote(h, 60) for h in headings[:3]) + _more(len(headings) - 3, lang)
        if lang == "tr":
            own = f"sayfanın dili {_lang(declared, lang)} (<html lang>)" + (
                f", metni {_lang(detected, lang)}" if detected else "")
            return f"{own}; başlıklar {_lang(language, lang)}: {shown}"
        own = f"page language {_lang(declared, lang)} (<html lang>)" + (f", its text {_lang(detected, lang)}" if detected else "")
        return f"{own}; headings in {_lang(language, lang)}: {shown}"
    return row(make)


# ------------------------------------------------------------------------------------------------ STR-2 card headings

# A price next to a product name: a currency code or sign before or after a number.
CURRENCIES = "AED|USD|EUR|GBP|TRY|TL|SAR|QAR|KWD|BHD|OMR|INR|CHF|SEK|NOK|DKK|PLN|JPY|CNY|AUD|CAD|RUB|ZAR|MXN|BRL"
PRICE = re.compile(r"(?:[$€£₺¥₹]|\b(?:" + CURRENCIES + r")\b)\s?\d|\d[\d.,]*\s?(?:[$€£₺¥₹]|\b(?:" + CURRENCIES + r")\b)",
                   re.IGNORECASE)
CARD_WINDOW = 4  # text lines after a heading in which its price is looked for
CARD_MIN = 6  # headings with a price after them before a page is said to mark product names as headings


def card_headings(headings: list[dict], lines: list[str] | None) -> list[dict]:
    """The <h2>/<h3> headings followed, within CARD_WINDOW lines of the page's text and before the next heading, by a
    price: a product card's name marked as a heading. `lines`: the page's text, one text node per line."""
    if not lines:
        return []
    texts = [" ".join(str(x).split()) for x in lines]
    names = {" ".join(str(h.get("text") or "").split()) for h in headings if isinstance(h, dict)}
    out, at = [], 0
    for h in headings:
        if not isinstance(h, dict) or h.get("level") not in (2, 3):
            continue
        text = " ".join(str(h.get("text") or "").split())
        if not text:
            continue
        try:
            i = texts.index(text, at)
        except ValueError:
            continue
        at = i + 1
        for line in texts[i + 1: i + 1 + CARD_WINDOW]:
            if line in names:
                break
            if PRICE.search(line):
                out.append(h)
                break
    return out


def card_headings_row(h2: int, cards: list[dict], sections: list[str]) -> dict:
    def make(lang):
        shown = ", ".join(quote(h.get("text"), 50) for h in cards[:3])
        if lang == "tr":
            line = f"{h2} H2 başlığın {len(cards)} tanesi ürün kartı adı: {shown}"
            return line + (f"; bölüm başlıkları: {', '.join(quote(s, 40) for s in sections[:2])}" if sections else "")
        line = f"{len(cards)} of {h2} <h2> headings are product card names: {shown}"
        return line + (f"; section headings: {', '.join(quote(s, 40) for s in sections[:2])}" if sections else "")
    return row(make)


# ------------------------------------------------------------------------------------------------ IDX-4 canonical

def _norm(url) -> str:
    return str(url or "").rstrip("/")


def canonical_versions(raw: list | None, rendered: dict | None, firecrawl: dict | None) -> dict:
    """Every reading of one page's canonical and what may be said from them.

    `raw`: the canonicals of the raw HTML. `rendered`: {"canonicals", "settled", "read_at"} of Maya's browser reading.
    `firecrawl`: {"canonicals", "read_at"} of the page reader's copy. The verdict: "differ" when two readings name
    different canonicals; "not_final" when the only browser reading was taken before the page finished loading (the
    final canonical, the one Google indexes after rendering, is then not known); else "agree" ("raw_only" when no
    browser reading was made)."""
    versions = []
    if raw:
        versions.append({"reading": "raw", "canonical": raw[0]})
    if isinstance(rendered, dict) and rendered.get("canonicals") is not None:
        versions.append({"reading": "rendered", "canonical": (rendered.get("canonicals") or [None])[0],
                         "settled": bool(rendered.get("settled")), "read_at": rendered.get("read_at")})
    if isinstance(firecrawl, dict) and firecrawl.get("canonicals") is not None:
        versions.append({"reading": "firecrawl", "canonical": (firecrawl.get("canonicals") or [None])[0],
                         "settled": True, "read_at": firecrawl.get("read_at")})
    values = {_norm(v["canonical"]) for v in versions}
    browser = [v for v in versions if v["reading"] != "raw"]
    if len(values) > 1:
        verdict = "differ"
    elif browser and not any(v.get("settled") for v in browser):
        verdict = "not_final"
    else:
        verdict = "agree" if browser else "raw_only"
    return {"versions": versions, "verdict": verdict}


READING = {"tr": {"raw": "ham HTML", "rendered": "tarayıcıda işlenmiş", "firecrawl": "Firecrawl kopyası"},
           "en": {"raw": "raw HTML", "rendered": "rendered in a browser", "firecrawl": "Firecrawl copy"}}


def canonical_row(found: dict) -> dict:
    def make(lang):
        parts = []
        for v in found["versions"]:
            when = str(v.get("read_at") or "")[:10]
            extra = []
            if when:
                extra.append(when)
            if v["reading"] == "rendered" and not v.get("settled"):
                extra.append("sayfa yüklenmesi bitmeden okundu" if lang == "tr" else "read before the page finished loading")
            none = "yok" if lang == "tr" else "none"
            parts.append(f"{READING[lang][v['reading']]}: {v.get('canonical') or none}" + (f" ({', '.join(extra)})" if extra else ""))
        return "; ".join(parts)
    return row(make)


# ------------------------------------------------------------------------------------------------ RND-1 and RND-3

ELEMENT = {"tr": {"heading": "başlık H{n}", "button": "düğme", "link": "bağlantı", "text": "metin"},
           "en": {"heading": "heading H{n}", "button": "button", "link": "link", "text": "text"}}


def locate_blocks(blocks: list[str], headings: list[dict] | None, buttons: list | None, anchors: list | None,
                  lines: list[str] | None = None) -> list[dict]:
    """Each missing text block with its element (a heading of its level, a button, a link, or text) and its section:
    the heading above it in the page's text (`lines`, when kept), else the last missing block that was a heading."""
    level = {" ".join(str(h.get("text") or "").split()): h.get("level") for h in headings or [] if isinstance(h, dict)}
    pressed = {" ".join(str(b.get("text") if isinstance(b, dict) else b or "").split()) for b in buttons or []}
    linked = {" ".join(str(a or "").split()) for a in anchors or []}
    texts = [" ".join(str(x).split()) for x in lines or []]
    out, section = [], None
    for block in blocks:
        text = " ".join(str(block or "").split())
        if not text:
            continue
        if text in level:
            element = {"kind": "heading", "level": level[text]}
        elif text in pressed:
            element = {"kind": "button"}
        elif text in linked:
            element = {"kind": "link"}
        else:
            element = {"kind": "text"}
        here = section
        if texts and text in texts:
            above = [t for t in texts[:texts.index(text)] if t in level]
            here = above[-1] if above else here
        out.append({"text": text[:QUOTE_CHARS * 2], "element": element, "section": here if here != text else None})
        if element["kind"] == "heading":
            section = text
    return out


def _element(e: dict, lang: str) -> str:
    return ELEMENT[lang][e["kind"]].format(n=e.get("level") or "")


def missing_row(located: list[dict], limit: int = 4) -> dict:
    def make(lang):
        parts = []
        for b in located[:limit]:
            where = [_element(b["element"], lang)]
            if b.get("section"):
                where.append(("bölüm " if lang == "tr" else "section ") + quote(b["section"], 40))
            parts.append(f"{quote(b['text'])} ({', '.join(where)})")
        head = "JavaScript'le gelen metin: " if lang == "tr" else "text that arrives with JavaScript: "
        return head + "; ".join(parts) + _more(len(located) - limit, lang)
    return row(make)


def revealed_row(clicked: list[dict], new_headings: list[str], sample: str | None, words_only: bool = False) -> dict:
    """`words_only`: the sample is the run of new words an older audit kept (lower-cased, without its common words),
    not a text block as the page writes it; it is said so."""
    def make(lang):
        parts = []
        if clicked:
            names = ", ".join(f"{quote(c.get('text'), 50)} (<{c.get('tag') or 'button'}>)" for c in clicked[:2])
            parts.append(("tıklanan: " if lang == "tr" else "clicked: ") + names + _more(len(clicked) - 2, lang))
        else:
            parts.append("sayfa kaydırılınca yüklenen içerik" if lang == "tr" else "content loaded on scroll")
        if new_headings:
            parts.append(("sonra görünen başlıklar: " if lang == "tr" else "headings shown after it: ")
                         + ", ".join(quote(h, 50) for h in new_headings[:3]) + _more(len(new_headings) - 3, lang))
        elif sample and words_only:
            parts.append(("sonra görünen kelimeler (örnek): " if lang == "tr" else "words shown after it (sample): ") + quote(sample))
        elif sample:
            parts.append(("sonra görünen metin: " if lang == "tr" else "text shown after it: ") + quote(sample))
        return "; ".join(parts)
    return row(make)


# ------------------------------------------------------------------------------------------------ STR-19, TSEO-1, STR-14

WHY_NO_ADDRESS = {"tr": {"empty href": "href boş", "no href": "href yok", "#": "href yalnızca «#»",
                         "javascript": "href bir betik (javascript:)"},
                  "en": {"empty href": "empty href", "no href": "no href", "#": "href is only «#»",
                         "javascript": "href is a script (javascript:)"}}


def _why(why: str, lang: str) -> str:
    text = str(why or "")
    for key, word in WHY_NO_ADDRESS[lang].items():
        if key in text.lower():
            return word
    return text or ("adres yok" if lang == "tr" else "no address")


def link_no_address_row(text: str, why: str, component: str | None) -> dict:
    def make(lang):
        place = (f"; her sayfada tekrarlanan alanda ({component})" if lang == "tr" else f"; in the block repeated on every page ({component})") if component else ""
        name = "bağlantısı" if lang == "tr" else "link"
        return f"{quote(text, 50)} {name}: <a> {_why(why, lang)}{place}"
    return row(make)


STOP_SLUG = frozenset("the a an and or of to in on for with at by from your our is are how what why part ve ile bir için "
                      "da de bu".split())


def slug_suggestion(slug: str, title: str | None = None, words: int = 6, limit: int = 60) -> str | None:
    """A short slug made of the address's own words (or the page title's when the address is only an id): stopwords and
    numbers left out, at most `words` words and `limit` characters."""
    def ascii_words(text):
        folded = unicodedata.normalize("NFKD", text.replace("ı", "i").replace("İ", "i")).encode("ascii", "ignore").decode()
        return [w for w in re.split(r"[^a-z0-9]+", folded.lower()) if w]
    pool = [w for w in ascii_words(unquote(slug)) if w not in STOP_SLUG and not w.isdigit() and len(w) > 1]
    if len(pool) < 2 and title:
        pool = [w for w in ascii_words(title) if w not in STOP_SLUG and not w.isdigit() and len(w) > 1]
    out = []
    for w in pool:
        if w in out:
            continue
        if len("-".join(out + [w])) > limit or len(out) >= words:
            break
        out.append(w)
    return "-".join(out) if len(out) >= 2 else None


REASONS = {"tr": {"over 100 characters": "100 karakterden uzun", "id only": "yalnızca bir kimlik/numara",
                  "space or symbol": "boşluk ya da simge içeriyor"},
           "en": {"over 100 characters": "over 100 characters", "id only": "only an id or number",
                  "space or symbol": "has a space or symbol"}}


def slug_row(url: str, why: str, title: str | None = None) -> dict:
    slug = unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
    better = slug_suggestion(slug, title)

    def make(lang):
        reason = next((w for k, w in REASONS[lang].items() if k in str(why or "")), str(why or ""))
        line = (f"kısa ad {quote(slug, 60)} ({len(slug)} karakter, {reason})" if lang == "tr" else
                f"slug {quote(slug, 60)} ({len(slug)} characters, {reason})")
        if better:
            line += (f"; öneri: «{better}»" if lang == "tr" else f"; suggested: «{better}»")
        return line
    return row(make)


def generic_links_row(links: list[dict]) -> dict:
    def make(lang):
        parts = []
        for x in links[:3]:
            target = urlsplit(str(x.get("target") or ""))
            path = (target.path or "/") + (f"?{target.query}" if target.query else "")
            place = ("menüde" if lang == "tr" else "in the menu") if x.get("in_navigation") else (
                "içerikte" if lang == "tr" else "in the content")
            parts.append(f"{quote(x.get('anchor'), 40)} → {path} ({place})")
        head = "hedefi söylemeyen bağlantı metni: " if lang == "tr" else "link text that does not name its target: "
        return head + "; ".join(parts) + _more(len(links) - 3, lang)
    return row(make)


def file_name(address: str) -> str:
    """The file name of an image address, read through an image proxy's url parameter."""
    from .file_names import file_address
    inner = file_address(address) or address
    return unquote(urlsplit(inner).path.rstrip("/").rsplit("/", 1)[-1]) or inner


def image_size_row(address: str, size: int, limit: int | None) -> dict:
    def make(lang):
        kb = round(size / 1024)
        cap = f" ({'sınır' if lang == 'tr' else 'limit'} {round(limit / 1024)} KB)" if limit else ""
        video = address.lower().split("?")[0].endswith((".mp4", ".webm", ".mov", ".m4v"))
        what = ("video" if video else "görsel") if lang == "tr" else ("video" if video else "image")
        shown = f"{kb / 1024:.1f} MB".replace(".", "," if lang == "tr" else ".") if kb >= 1024 else f"{kb} KB"
        return f"{what} {quote(file_name(address), 70)}: {shown}{cap}"
    return row(make)


PLACES = {"tr": {"footer": "alt bilgide (footer)", "header": "üst bilgide (header)", "nav": "menüde"},
          "en": {"footer": "in the footer", "header": "in the header", "nav": "in the menu"}}


def heading_jump_row(text: str, level: int, after: int, where: str | None) -> dict:
    def make(lang):
        place = PLACES[lang].get(where or "", "")
        if lang == "tr":
            return f"{quote(text, 60)} başlığı H{level}, sayfadaki H{after} başlığından sonra geliyor (aradaki düzey atlanıyor)" + (f"; {place}" if place else "")
        return f"{quote(text, 60)} is an H{level} after the page's H{after} (a level is skipped)" + (f"; {place}" if place else "")
    return row(make)


def no_author_row(title: str | None) -> dict:
    def make(lang):
        name = quote(title, 70) if title else ("bu makale" if lang == "tr" else "this article")
        return (f"makale {name}: yazar adı yok (byline, rel=author, <meta name=\"author\"> ve yapısal veride author bulunamadı)"
                if lang == "tr" else
                f"article {name}: no author named (no byline, rel=author, <meta name=\"author\"> or author in structured data)")
    return row(make)


def jump_row(example: dict) -> dict:
    def make(lang):
        a, b = example.get("from"), example.get("to")
        if lang == "tr":
            return f"{quote(example.get('text'), 70)} başlığı H{b}, önceki başlık H{a} (aradaki düzey atlanıyor)"
        return f"{quote(example.get('text'), 70)} is an H{b} after an H{a} (a level is skipped)"
    return row(make)


def h1_row(state: str, title: str | None) -> dict:
    def make(lang):
        what = {"absent": ("<h1> etiketi yok", "no <h1> tag"), "empty": ("<h1> etiketi boş: <h1></h1>", "the <h1> is empty: <h1></h1>")}
        said = what.get(state, what["absent"])[0 if lang == "tr" else 1]
        return said + ((f"; sayfa başlığı (title) {quote(title, 70)}" if lang == "tr" else f"; page title {quote(title, 70)}")
                       if title else "")
    return row(make)


def copies_row(others: list[str], similarity: float | None) -> dict:
    def make(lang):
        paths = ", ".join((urlsplit(u).path or "/") for u in others[:2])
        share = f" (benzerlik %{round(similarity * 100)})" if similarity and lang == "tr" else (
            f" (similarity {round(similarity * 100)}%)" if similarity else "")
        return (f"ana metni şu sayfayla aynı: {paths}{share}" if lang == "tr" else f"same main text as {paths}{share}")
    return row(make)


def differs_row(field: str, schema_value, visible) -> dict:
    shown = visible.get("text") if isinstance(visible, dict) else (
        (visible[0].get("text") if visible and isinstance(visible[0], dict) else visible[0]) if isinstance(visible, list) and visible else visible)

    def make(lang):
        return (f"yapısal veride {field} {quote(schema_value, 50)}, sayfada {quote(shown, 50)}" if lang == "tr" else
                f"structured data {field} {quote(schema_value, 50)}, on the page {quote(shown, 50)}")
    return row(make)


def unparsed_row(block: dict) -> dict:
    def make(lang):
        where = f"satır {block.get('line')}" if lang == "tr" else f"line {block.get('line')}"
        bad = block.get("character") or block.get("error_type") or block.get("error")
        return (f"JSON-LD blok {block.get('index', 0) + 1}, {where}: {bad}; {quote(block.get('excerpt') or block.get('snippet'), 80)}"
                if lang == "tr" else
                f"JSON-LD block {block.get('index', 0) + 1}, {where}: {bad}; {quote(block.get('excerpt') or block.get('snippet'), 80)}")
    return row(make)


# ------------------------------------------------------------------------------------------------ on a report

def _findings(report: dict, rule: str):
    for check in report.get("checks") or []:
        for f in check.get("findings") or []:
            if f.get("rule_id") == rule or (rule.endswith((".", "_")) and str(f.get("rule_id") or "").startswith(rule)):
                yield f


def attach(report: dict) -> list[str]:
    """Each page's own line on the findings of a report (JSON form) that lack one: the shared link with no address,
    unclear slugs, generic link texts, content shown after a click or scroll and content missing from the raw HTML.
    Read from the finding's evidence and the saved browser readings (`crawl.render.pages`); a line already written is
    kept. Returns the ids of the findings given lines."""
    crawl = report.get("crawl") or {}
    render = (crawl.get("render") or {}).get("pages") or {}
    titles = {p.get("url"): (p.get("analysis") or {}).get("title") for p in crawl.get("pages") or [] if isinstance(p, dict)}
    done: list[str] = []

    def put(rec: dict, value: dict, fid: str) -> None:
        if isinstance(rec, dict) and not isinstance(rec.get("row"), dict):
            rec["row"] = value
            if fid not in done:
                done.append(fid)

    for f in _findings(report, "shared.link_no_address"):
        ev = f.get("evidence") or {}
        el = ev.get("shared_element") or {}
        if el.get("text") is not None:
            line = link_no_address_row(el.get("text"), el.get("why"), el.get("component"))
            for rec in ev.get("by_page") or []:
                put(rec, line, f["id"])
    for f in _findings(report, "tseo1.url_slug_unclear"):
        for rec in (f.get("evidence") or {}).get("pages") or []:
            if isinstance(rec, dict) and rec.get("url"):
                put(rec, slug_row(rec["url"], rec.get("why"), titles.get(rec["url"])), f["id"])
    for f in _findings(report, "judgment.generic."):
        links = [x for x in (f.get("evidence") or {}).get("links") or [] if isinstance(x, dict) and x.get("source")]
        by_source: dict[str, list[dict]] = {}
        for x in links:
            by_source.setdefault(x["source"], []).append(x)
        for x in links:
            put(x, generic_links_row(by_source[x["source"]]), f["id"])
    for f in _findings(report, "rnd3.revealed"):
        for rec in (f.get("evidence") or {}).get("pages") or []:
            if not isinstance(rec, dict) or not rec.get("url"):
                continue
            inter = (render.get(rec["url"]) or {}).get("interaction") or {}
            before = (inter.get("control") or {}).get("headings") or []
            after = (inter.get("after") or {}).get("headings") or []
            had = {" ".join(str(h.get("text") or "").split()) for h in before if isinstance(h, dict)}
            new = [str(h.get("text") or "")[:120] for h in after if isinstance(h, dict)
                   and " ".join(str(h.get("text") or "").split()) not in had][:10]
            blocks = rec.get("new_text_blocks") or []
            put(rec, revealed_row(rec.get("clicked") or [], rec.get("new_headings") or new,
                                  blocks[0] if blocks else rec.get("new_text_sample"), words_only=not blocks), f["id"])
    # Findings whose records are not one per page get a list of page lines beside them (`page_lines`), which
    # "Bulgu bazında" reads the same way.
    def lines(f: dict, made: list[dict]) -> None:
        ev = f.setdefault("evidence", {})
        if made and not ev.get("page_lines"):
            ev["page_lines"] = made
            done.append(f["id"])
    heavy = [*_findings(report, "str7.over_"), *_findings(report, "str7.heavy"), *_findings(report, "str7.video")]
    for f in heavy:
        ev = f.get("evidence") or {}
        limit = (ev.get("thresholds_bytes") or {}).get("from")
        made, seen = [], set()
        for img in (ev.get("images") or []) + (ev.get("videos") or []):
            if not isinstance(img, dict) or not isinstance(img.get("bytes"), int):
                continue
            address = str(img.get("image") or img.get("video") or "")
            line = image_size_row(address, img["bytes"], limit)
            for at in [address] + list(img.get("shown_on") or []):  # the rows are by image or by page
                if at and at not in seen:
                    seen.add(at)
                    made.append({"url": at, "row": line})
        lines(f, made)
    for f in _findings(report, "shared.heading_jump"):
        ev = f.get("evidence") or {}
        el = ev.get("shared_element") or {}
        if el.get("text"):
            lines(f, [{"url": x["url"], "row": heading_jump_row(el["text"], x.get("to") or el.get("level") or 0,
                                                                  x.get("from") or 1, el.get("where"))}
                      for x in ev.get("items") or [] if isinstance(x, dict) and x.get("url")])
    for f in _findings(report, "tseo1.heading_jumps"):
        made = []
        for item in (f.get("evidence") or {}).get("items") or []:
            ex = next((x for x in (item or {}).get("examples") or [] if isinstance(x, dict) and str(x.get("text") or "").strip()), None)
            if ex and item.get("url"):
                made.append({"url": item["url"], "row": jump_row(ex)})
        lines(f, made)
    for rule in ("str2.no_h1", "str2.home_no_h1", "str2.empty_h1"):
        for f in _findings(report, rule):
            state = "empty" if rule == "str2.empty_h1" else "absent"
            urls = [u for u in (f.get("evidence") or {}).get("pages") or [] if isinstance(u, str)] or (f.get("scope") or {}).get("urls") or []
            lines(f, [{"url": u, "row": h1_row(state, titles.get(u))} for u in urls])
    for f in _findings(report, "idx8.copies"):
        made = []
        for group in (f.get("evidence") or {}).get("duplicate_groups") or []:
            urls = [u for u in (group or {}).get("urls") or [] if isinstance(u, str)]
            pairs = {(p.get("a"), p.get("b")): p.get("estimated_similarity") for p in group.get("pairs") or [] if isinstance(p, dict)}
            for u in urls:
                others = [o for o in urls if o != u]
                share = next((v for (a, b), v in pairs.items() if u in (a, b)), None)
                made.append({"url": u, "row": copies_row(others, share)})
        lines(f, made)
    for f in _findings(report, "str4.differs"):
        for rec in (f.get("evidence") or {}).get("values") or []:
            if isinstance(rec, dict) and rec.get("url") and rec.get("schema_value") is not None and rec.get("visible"):
                put(rec, differs_row(rec.get("field") or rec.get("property") or "", rec["schema_value"], rec["visible"]), f["id"])
    for f in _findings(report, "str3.unparsed"):
        for rec in (f.get("evidence") or {}).get("pages") or []:
            block = next((b for b in (rec or {}).get("blocks") or [] if isinstance(b, dict) and not b.get("ok")), None)
            if block:
                put(rec, unparsed_row(block), f["id"])
    for f in _findings(report, "str3.article_no_author"):
        urls = (f.get("scope") or {}).get("urls") or []
        lines(f, [{"url": u, "row": no_author_row(titles.get(u))} for u in urls])
    for rule in ("rnd1.partial", "rnd1.missing"):
        for f in _findings(report, rule):
            for rec in (f.get("evidence") or {}).get("pages") or []:
                delta = (rec or {}).get("content_delta") if isinstance(rec, dict) else None
                if not isinstance(delta, dict) or not delta.get("missing_text_blocks"):
                    continue
                entry = render.get(rec.get("url")) or {}
                shown = entry.get("rendered") or {}
                located = delta.get("located") or locate_blocks(
                    [b.get("text") for b in delta["missing_text_blocks"] if isinstance(b, dict)],
                    shown.get("headings") or rec.get("headings_only_after_render"), shown.get("buttons"),
                    [x.get("anchor") for x in entry.get("rendered_links") or [] if isinstance(x, dict)])
                if located:
                    put(rec, missing_row(located), f["id"])
    return done


# ------------------------------------------------------------------------------------------------ the Özet's example

# Evidence fields that hold a concrete thing seen on a page, in the order they are preferred, with their name.
FIELDS = (("text", "metin", "text"), ("anchor", "bağlantı metni", "link text"), ("texts", "metin", "text"),
          ("h1", "H1", "H1"), ("src", "görsel", "image"), ("image", "görsel", "image"), ("video", "video", "video"),
          ("iframe_src", "iframe", "iframe"), ("href", "href", "href"), ("next", "sonraki sayfa", "next page"),
          ("target", "hedef", "target"), ("element", "öğe", "element"), ("container", "öğe", "element"),
          ("component", "öğe", "element"), ("sameAs", "sameAs", "sameAs"), ("snippet", "kod", "code"),
          ("examples", "örnek", "example"), ("sitemap", "site haritası", "sitemap"), ("file", "dosya", "file"))
NOT_EVIDENCE = frozenset({"severity_assessment", "judgment", "source", "reading", "verification", "reproduce",
                          "regions", "retrieval_membership", "heading_assessments", "facts"})
PAGE_KEYS = ("url", "source", "page", "example")


def _first_value(value):
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for v in value:
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict) and isinstance(v.get("text"), str) and v["text"].strip():
                return v["text"].strip()
    return None


def evidence_example(finding: dict, lang: str = "tr") -> str | None:
    """'page: field «value»' from the first evidence record that names a page and a concrete thing seen there (link
    text, image, element, next page...), for a finding whose page lines show only counts. None when there is none."""
    ev = finding.get("evidence") or {}
    records = []
    if isinstance(ev.get("shared_element"), dict):
        page = next((x.get("source") or x.get("example") for x in ev.get("links") or [] if isinstance(x, dict)), None)
        records.append({**ev["shared_element"], "url": page or ((finding.get("scope") or {}).get("urls") or [None])[0]})
    for key, value in ev.items():
        if key in NOT_EVIDENCE or not isinstance(value, list):
            continue
        records += [x for x in value if isinstance(x, dict)]
    for rec in records:
        page = next((rec[k] for k in PAGE_KEYS if isinstance(rec.get(k), str) and rec[k].startswith("http")), None)
        if not page:
            continue
        for key, tr, en in FIELDS:
            found = _first_value(rec.get(key))
            if found and found.rstrip("/") != page.rstrip("/"):
                parts = urlsplit(page)
                where = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
                return f"{where}: {tr if lang == 'tr' else en} {quote(found, 90)}"
    return None
