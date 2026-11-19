"""The release gate's text checks (DECISIONS 353): what a report says, read before every download.

`release_gate` checks that a card rests on its findings (addresses, re-tests, conditions). This module reads the words
the reader is given: the team report's data (`build_data`: cards, notes, the findings table, page 1) in the report's
language. It never changes a text: it returns violations, and the decision made from them (PASS, CONDITIONAL, BLOCKED,
as `release_gate.decision`). A BLOCKED text check makes the download a marked draft; it never deletes a card.

Rules (hard = the download is a draft, soft = listed in "Kontrol raporu"):
    RG-18 hard  a placeholder left in a text ({count}, [[...]], ⟪YAZ⟫, None), or a number in a card that none of the
                card's own findings holds (their title, evidence, scope and counts; another finding's numbers do not count)
    RG-19 hard  platform-specific advice (Shopify, WordPress, ...) on a site the report does not name as that platform
    RG-20 hard  advice to remove a menu or footer link, or a link to a sign-in or application entry
    RG-21 hard/soft  English left in a Turkish text: the "(İngilizce)" mark, or English words outside quoted site text
                (hard in a card's own lines: title, steps, why, verify; soft elsewhere)
    RG-22 hard  two cards that say the same thing (one rule or one title) about the same pages
    RG-23 soft  a phrase from the banned list (`banned_phrases.json`, the SEO team's file); a phrase marked
                "block": true is hard
    RG-24 soft  a problem the appendix's Özet does not list under "Diğer bulgular" because none of its pages shows a
                concrete example (quoted page text, an address or an element) (DECISIONS 368)

Global for every site: no brand, no address and no fixed title is named here; the phrase list is data.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

VERSION = "text-gate-1"
PHRASES_FILE = Path(__file__).with_name("banned_phrases.json")
PASS, CONDITIONAL, BLOCKED = "PASS", "CONDITIONAL", "BLOCKED"

# Platforms advice can be specific to (site_platform's names, and two Turkish e-commerce platforms it does not detect).
PLATFORMS = ("Shopify", "WordPress", "WooCommerce", "Magento", "Shopware", "PrestaShop", "OpenCart", "Squarespace",
             "Webflow", "Wix", "ikas", "Ticimax", "IdeaSoft", "T-Soft", "Drupal", "Joomla", "BigCommerce", "HubSpot")
BUILT_ON = {"WooCommerce": "WordPress"}
_PLATFORM = re.compile(r"(?<![\w.-])(" + "|".join(re.escape(p) for p in PLATFORMS) + r")(?![\w-])", re.IGNORECASE)

# Keys whose values are the site's own data or bookkeeping, never a sentence of the report.
SITE_DATA = frozenset({"links", "all_urls", "known_paths", "link_rows", "url_notes", "fact", "finding_ids", "id", "ref",
                       "url", "path", "href", "domain", "brand", "audit_id", "engine_version", "template", "kind_id",
                       "rule_id", "severity", "issue_type", "p_level", "confidence_class", "state", "lang", "key",
                       "evidence_sample", "search", "step_rules", "topics", "target_urls", "url_finding", "launch_gated",
                       "file", "cards", "date", "date_long", "coverage_level", "tone", "value", "of", "group", "item",
                       "checklist", "templates", "key_pages", "meta", "contract", "appendix"})
# The visible text fields of a card the reader acts on (RG-21 is hard there).
CARD_LINES = ("title", "steps", "why", "verify", "explanation", "finding")
CARD_LISTS = ("todos", "notes_more", "confirm", "findings")

PLACEHOLDER = re.compile(r"\{[\w:|!#~%*. -]*\}|\[\[|\]\]|⟪|⟫|\bNone\b|\bnull\b|\bundefined\b|\bNaN\b|%s\b|\{\}")
ENGLISH_MARK = re.compile(r"\((?:İngilizce|English)\)")
EN_WORDS = re.compile(r"\b(the|and|with|of|to|is|are|this|that|from|for|not|page|pages|was|were|should|your|link|links|"
                      r"which|have|has|been|will|can|its|on|by|at)\b", re.IGNORECASE)
# Quoted site text, markup, addresses and code names: never read as the report's own words or numbers.
# DECISIONS 361: a single quote opens only after a non-letter and closes before one: a Turkish suffix apostrophe
# ("GTIN'i", "Shopify'da") is not a quote, so the text between two of them is the report's own words
QUOTED = re.compile(r"«[^»]*»|\"[^\"]*\"|“[^”]*”|‘[^’]*’|(?<![\w])'[^'\s][^']*'(?![\w])|`[^`]*`")
MARKUP = re.compile(r"<[^<>]{1,80}>|https?://\S+|(?<![\w])/[\w\-./%?=&#~+]*|\b[\w-]+\.(?:txt|xml|json|js|css|html?|php)\b")
CODE_NUMBERS = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[./]\d{1,2}[./]\d{4}\b|\b[Hh][1-6]\b|\b[1-5]xx\b|\bUTF-?8\b|\bISO-\d+(?:-\d+)?\b|\bWCAG\s?\d(?:\.\d)?\b|\bHTTP/\d(?:\.\d)?\b|"
                          r"\bIPv[46]\b|\bP[0-3]\b|\bS[1-4]\b|\b[A-Z]{2,5}-\d+\b|\bx-default\b|\b\d+(?:\.\d+)?\s?(?:KB|KiB|MB|ms|px)\b|"
                          r"\b(?:Core Web Vitals|schema\.org)\b")
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# A step or a line that tells the reader to remove a link.
REMOVE = re.compile(r"\b(?:kaldırın|kaldırılmalı|silin|silinmeli|çıkarın|remove|delete)\b", re.IGNORECASE)
LINK_WORD = re.compile(r"\b(?:bağlantı\w*|link\w*|menü\w*|menu\w*)\b", re.IGNORECASE)
ENTRY_RULES = frozenset({"idx6.links_to_login_redirect", "idx6.links_to_entry_redirect"})
ENTRY_PATH = re.compile(r"(?:^|/)(?:login|signin|sign-in|giris|giriş|uye-girisi|uyegirisi|hesabim|my-?account|account|"
                        r"basvuru|başvuru|apply|register|kayit|kayıt|sepet|cart|checkout)(?:[/?#.]|$)", re.IGNORECASE)
NAV_WORD = re.compile(r"\b(?:menü|menu|alt bilgi|footer|navigasyon|navigation)\w*", re.IGNORECASE)
KEEP = re.compile(r"\b(?:kaldırmayın|silmeyin|tutun|do not remove|don't remove|keep)\b", re.IGNORECASE)
NAV_PLACES = frozenset({"menu", "footer", "nav", "header"})


def violation(rule: str, message: str, *, hard: bool, where: str | None = None, text: str | None = None,
              card: int | None = None) -> dict:
    row: dict[str, Any] = {"rule": rule, "hard": hard, "message": message}
    if where:
        row["where"] = where
    if text:
        row["text"] = text[:200]
    if card is not None:
        row["card"] = card
    return row


def decision(violations: list[dict]) -> str:
    if any(v["hard"] for v in violations):
        return BLOCKED
    return CONDITIONAL if violations else PASS


# ---------------------------------------------------------------- the banned phrases (the SEO team's file)

@lru_cache(maxsize=4)
def _phrases_cached(path: str, stamp: float) -> tuple[dict, ...]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for row in data.get("phrases") or []:
        text = str(row.get("text") or "").strip()
        if text:
            out.append({"text": text, "lang": row.get("lang") or "tr", "block": bool(row.get("block")),
                        "why": row.get("why") or "", "instead": row.get("instead") or ""})
    return tuple(out)


def phrases(path: Path | None = None) -> tuple[dict, ...]:
    """The banned phrases: the SEO team edits `banned_phrases.json`; a change counts on the next report."""
    p = Path(path or PHRASES_FILE)
    if not p.is_file():
        return ()
    return _phrases_cached(str(p), p.stat().st_mtime)


def fold(text: str) -> str:
    """Lower case the Turkish way ("İ" -> "i", "I" -> "ı"), spaces collapsed: how a phrase is matched."""
    return re.sub(r"\s+", " ", text.replace("İ", "i").replace("I", "ı").lower()).strip()


# ---------------------------------------------------------------- reading the texts

def texts_of(data: dict) -> list[tuple[str, str, int | None]]:
    """(where, text, card number) for every sentence the reader is shown; site data and private keys left out."""
    out: list[tuple[str, str, int | None]] = []

    def walk(value: Any, where: str, card: int | None) -> None:
        if isinstance(value, str):
            if value.strip():
                out.append((where, value, card))
        elif isinstance(value, dict):
            for key, item in value.items():
                if key in SITE_DATA or str(key).startswith("_"):
                    continue
                walk(item, f"{where}.{key}" if where else str(key), card)
        elif isinstance(value, list):
            for n, item in enumerate(value):
                walk(item, f"{where}[{n}]", card)

    for key, value in data.items():
        if key.startswith("_") or key in SITE_DATA:
            continue
        if key in ("todos", "notes_more") and isinstance(value, list):
            for n, card in enumerate(value):
                number = card.get("n") if isinstance(card, dict) and isinstance(card.get("n"), int) else None
                walk(card, f"{key}[{n}]", number if key == "todos" else None)
            continue
        walk(value, key, None)
    return out


def _plain(text: str) -> str:
    """The report's own words: quoted site text, markup and addresses taken out."""
    return MARKUP.sub(" ", QUOTED.sub(" ", text))


def _numbers(text: str) -> set[str]:
    return {norm(n) for n in NUMBER.findall(CODE_NUMBERS.sub(" ", _plain(text)))}


def norm(n: str) -> str:
    """'40,500' / '40.500' -> '40500'; '5,2' -> '5.2'."""
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", n):
        return re.sub(r"[.,]", "", n)
    return n.replace(",", ".")


def _all_numbers(value: Any, out: set[str]) -> set[str]:
    if isinstance(value, bool) or value is None:
        return out
    if isinstance(value, (int, float)):
        out.add(str(int(value)) if float(value).is_integer() else str(value))
        if isinstance(value, float):
            out.update({f"{value:.1f}", f"{value:.0f}", f"{value * 100:.0f}"})
    elif isinstance(value, str):
        out.update(norm(n) for n in NUMBER.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            _all_numbers(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _all_numbers(v, out)
    return out


def _findings(report: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for check in (report.get("checks") or []) + (report.get("answer_engine_panel") or []):
        for finding in check.get("findings") or []:
            if finding.get("id"):
                out[finding["id"]] = finding
    return out


def _cards(data: dict) -> list[tuple[str, int, dict]]:
    return [(key, n, card) for key in ("todos", "notes_more") for n, card in enumerate(data.get(key) or [])
            if isinstance(card, dict)]


def _card_text(card: dict) -> list[tuple[str, str]]:
    rows = []
    for field in CARD_LINES + ("scope", "sub", "status", "when"):
        value = card.get(field)
        for line in (value if isinstance(value, list) else [value]):
            if isinstance(line, str) and line.strip():
                rows.append((field, line))
    return rows


def _label(key: str, n: int, card: dict) -> str:
    number = card.get("n")
    return f"kart {number}" if key == "todos" and number else f"not kartı {n + 1}" if key == "notes_more" else f"{key}[{n}]"


# ---------------------------------------------------------------- the rules

def check(data: dict, report: dict | None = None, *, lang: str | None = None, platform: str | None = None,
          banned: Iterable[dict] | None = None) -> list[dict]:
    """Every text violation of one team report's data against the report it was built from."""
    report = report or {}
    lang = lang or data.get("lang") or "tr"
    platform = platform if platform is not None else ((report.get("platform") or {}).get("name") or "")
    out: list[dict] = []
    texts = texts_of(data)

    # RG-18: placeholders anywhere the reader looks.
    for where, text, card in texts:
        hit = PLACEHOLDER.search(text)
        if hit:
            out.append(violation("RG-18", f"{where}: yer tutucu kalmış ({hit.group(0)})", hard=True, where=where,
                                 text=text, card=card))

    # RG-18: a number a card says that none of its findings holds.
    by_id = _findings(report)
    for key, n, card in _cards(data):
        mine = [by_id[i] for i in card.get("finding_ids") or [] if i in by_id]
        if not mine:
            continue
        allowed = _all_numbers(mine, set())
        allowed |= _all_numbers([len(card.get("all_urls") or []), card.get("more"), card.get("unlisted"),
                                 len(card.get("finding_ids") or []), card.get("fact"), card.get("url_notes"),
                                 card.get("link_rows")], set())
        for field, line in _card_text(card):
            if field == "sub":
                continue  # the evidence lines are the findings' own words
            wrong = sorted(x for x in _numbers(line) if x not in allowed)
            if wrong:
                out.append(violation("RG-18", f"{_label(key, n, card)} {field}: '{wrong[0]}' sayısı kartın kendi bulgularında yok "
                                              "(başlık, kanıt, kapsam)", hard=True, where=f"{key}[{n}].{field}", text=line,
                                     card=card.get("n") if key == "todos" else None))

    # RG-19: platform-specific advice on another platform.
    own = {platform.lower(), BUILT_ON.get(platform, "").lower()} - {""}
    # DECISIONS 361: the platform must be in the site's own data, never in an advice text of the findings (MMI's GTIN fix
    # named Shopify, so "Shopify" was found "in the evidence" and the card's Shopify step passed)
    advice_keys = ("how_to_fix", "expected", "notes", "judgment", "fix", "page_fixes", "rationale")

    def site_data(f):
        if not isinstance(f, dict):
            return f
        return {k: (site_data(v) if isinstance(v, dict) else v) for k, v in f.items() if k not in advice_keys}
    for key, n, card in _cards(data):
        evidence = json.dumps([site_data(by_id.get(i)) for i in card.get("finding_ids") or []], ensure_ascii=False, default=str).lower()
        for field, line in _card_text(card):
            if field == "sub":
                continue
            for hit in _PLATFORM.finditer(_plain(line)):
                name = hit.group(1)
                if name.lower() in own or name.lower() in evidence:
                    continue
                said = f"sitenin platformu {platform}" if platform else "rapor sitenin platformunu belirlemedi"
                out.append(violation("RG-19", f"{_label(key, n, card)} {field}: {name}'a özgü öneri; {said}", hard=True,
                                     where=f"{key}[{n}].{field}", text=line, card=card.get("n") if key == "todos" else None))
                break

    # RG-20: removing a menu, footer or sign-in link.
    for key, n, card in _cards(data):
        label = _label(key, n, card)
        rows = card.get("link_rows") or []
        for r in rows:
            if not isinstance(r, dict) or r.get("suggested") not in ("remove", "remove_or_redirect"):
                continue
            to = str(r.get("links_to") or r.get("target_url") or r.get("href") or "")
            if r.get("position") in NAV_PLACES:
                out.append(violation("RG-20", f"{label}: {r.get('position')} bağlantısı için 'kaldırın' öneriliyor "
                                              f"({r.get('href') or to}); menü bağlantısı düzeltilir, kaldırılmaz",
                                     hard=True, where=f"{key}[{n}].link_rows", text=to, card=card.get("n") if key == "todos" else None))
                break
            if r.get("rule_id") in ENTRY_RULES or ENTRY_PATH.search(_path(to)):
                out.append(violation("RG-20", f"{label}: giriş/başvuru bağlantısı için 'kaldırın' öneriliyor ({to})",
                                     hard=True, where=f"{key}[{n}].link_rows", text=to, card=card.get("n") if key == "todos" else None))
                break
        entry = card.get("rule_id") in ENTRY_RULES or any(
            (by_id.get(i) or {}).get("rule_id") in ENTRY_RULES for i in card.get("finding_ids") or [])
        for field, line in _card_text(card):
            plain = _plain(line)
            if not (REMOVE.search(plain) and LINK_WORD.search(plain)) or KEEP.search(plain):
                continue
            if entry or NAV_WORD.search(plain):
                out.append(violation("RG-20", f"{label} {field}: menü ya da giriş bağlantısını kaldırmayı öneriyor",
                                     hard=True, where=f"{key}[{n}].{field}", text=line, card=card.get("n") if key == "todos" else None))
                break

    # RG-21: English in a Turkish report.
    if lang == "tr":
        for where, text, card in texts:
            plain = _plain(text)
            mark = ENGLISH_MARK.search(text)
            words = sorted({w.lower() for w in EN_WORDS.findall(plain)})
            if not mark and len(words) < 2:
                continue
            on_card = bool(re.match(r"(?:todos|notes_more|confirm|findings)\[\d+\]\.(?:" + "|".join(CARD_LINES) + r")\b", where))
            said = "çevrilmemiş cümle (İngilizce işareti)" if mark else f"İngilizce kelimeler: {', '.join(words[:6])}"
            out.append(violation("RG-21", f"{where}: Türkçe metinde İngilizce kalmış ({said})", hard=on_card, where=where,
                                 text=text, card=card))

    # RG-22: two cards saying the same thing about the same pages.
    seen: dict[tuple, str] = {}
    for key, n, card in _cards(data):
        pages = frozenset(_path(u) for u in card.get("all_urls") or [])
        if not pages:
            continue
        label = _label(key, n, card)
        for sig in ((("rule", card.get("rule_id")) if card.get("rule_id") else None), ("title", fold(str(card.get("title") or "")))):
            if not sig or not sig[1]:
                continue
            first = seen.get((sig, pages))
            if first and first != label:
                what = "aynı kural" if sig[0] == "rule" else "aynı başlık"
                out.append(violation("RG-22", f"{first} ile {label} aynı sayfalar için {what} ({sig[1]})", hard=True,
                                     where=f"{key}[{n}]", text=str(card.get("title") or ""),
                                     card=card.get("n") if key == "todos" else None))
                break
            seen.setdefault((sig, pages), label)

    # RG-23: banned phrases.
    rows = list(banned) if banned is not None else list(phrases())
    for where, text, card in texts:
        folded = fold(_plain(text))
        for row in rows:
            if row.get("lang") not in (None, "", lang, "*"):
                continue
            if re.search(r"(?<!\w)" + re.escape(fold(row["text"])) + r"(?!\w)", folded):
                extra = f"; yerine: {row['instead']}" if row.get("instead") else ""
                out.append(violation("RG-23", f"{where}: yasaklı ifade «{row['text']}»{extra}", hard=bool(row.get("block")),
                                     where=where, text=text, card=card))
    return out


def _path(url: str) -> str:
    from urllib.parse import urlsplit
    if not url:
        return ""
    parts = urlsplit(url)
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "") if parts.scheme else url


def run(data: dict, report: dict | None = None, **kwargs) -> dict:
    """The text check's record: decision, violations and counts per rule (the "Kontrol raporu" sheet)."""
    violations = check(data, report, **kwargs)
    counts: dict[str, int] = {}
    for v in violations:
        counts[v["rule"]] = counts.get(v["rule"], 0) + 1
    return {"version": VERSION, "decision": decision(violations), "violations": violations, "counts": counts,
            "hard": sum(1 for v in violations if v["hard"])}


RULE_NAMES = {
    "tr": {"RG-18": "Yer tutucu ya da kanıtta olmayan sayı", "RG-19": "Başka platforma özgü öneri",
           "RG-20": "Menü ya da giriş bağlantısını kaldırma önerisi", "RG-21": "Türkçe metinde İngilizce",
           "RG-22": "Aynı sayfalar için tekrarlanan kart", "RG-23": "Yasaklı ifade",
           "RG-24": "Somut örneği olmayan bulgu", "LLM": "İkinci okuyucu önerisi"},
    "en": {"RG-18": "Placeholder or a number not in the evidence", "RG-19": "Advice for another platform",
           "RG-20": "Advice to remove a menu or sign-in link", "RG-21": "English left in Turkish text",
           "RG-22": "Card repeated for the same pages", "RG-23": "Banned phrase",
           "RG-24": "Finding with no concrete example", "LLM": "Second reader's suggestion"},
}


def with_platform_advice(record: dict | None, cells: Iterable[tuple[str, str]], platform: str | None,
                         lang: str = "tr") -> dict | None:
    """DECISIONS 361: RG-19 on the appendix's own advice ("Ne yapılmalı"): a cell naming another platform than the
    site's is a hard violation, once per platform and sheet."""
    if record is None:
        return record
    from .platform_text import other_platform
    seen, extra = set(), []
    for where, text in cells:
        name = other_platform(_plain(text), platform)
        if name and (where, name.lower()) not in seen:
            seen.add((where, name.lower()))
            said = f"sitenin platformu {platform}" if platform else "rapor sitenin platformunu belirlemedi"
            extra.append(violation("RG-19", f"Ek ({where}): {name}'a özgü öneri; {said}", hard=True,
                                   where=f"ek: {where}", text=text))
    if not extra:
        return record
    violations = list(record["violations"]) + extra
    counts = dict(record.get("counts") or {})
    counts["RG-19"] = counts.get("RG-19", 0) + len(extra)
    return {**record, "violations": violations, "counts": counts, "decision": decision(violations)}


def with_no_example(record: dict | None, names: Iterable[str], lang: str = "tr") -> dict | None:
    """DECISIONS 368: RG-24 (soft) for each problem the Özet leaves out of "Diğer bulgular" because none of its pages
    shows a concrete example; it stays in "Bulgular"."""
    if record is None:
        return record
    extra = []
    for name in dict.fromkeys(n for n in names if n):
        message = (f"Özet: «{name}» için somut örnek (sayfa ve metin/öğe) yok; «Diğer bulgular»da listelenmedi, «Bulgular»da duruyor"
                   if lang == "tr" else f"Summary: «{name}» has no concrete example (page and text/element); left out of "
                   "\"Other findings\", kept in \"Findings\"")
        extra.append(violation("RG-24", message, hard=False, where="ek: Özet", text=name))
    if not extra:
        return record
    violations = list(record["violations"]) + extra
    counts = dict(record.get("counts") or {})
    counts["RG-24"] = counts.get("RG-24", 0) + len(extra)
    return {**record, "violations": violations, "counts": counts, "decision": decision(violations)}


def with_untranslated(record: dict | None, sentences: Iterable[tuple[str, str]], lang: str = "tr") -> dict | None:
    """The record with RG-21 rows for the appendix's own sentences that had no translation (the "(İngilizce)" mark the
    wording shows them with): soft, once per sentence. `sentences`: (where, text)."""
    if record is None or lang != "tr":
        return record
    seen, extra = set(), []
    for where, text in sentences:
        if text in seen:
            continue
        seen.add(text)
        extra.append(violation("RG-21", f"Ek ({where}): Türkçe karşılığı olmayan cümle İngilizce gösteriliyor", hard=False,
                               where=f"ek: {where}", text=text))
    if not extra:
        return record
    violations = list(record["violations"]) + extra
    counts = dict(record.get("counts") or {})
    counts["RG-21"] = counts.get("RG-21", 0) + len(extra)
    return {**record, "violations": violations, "counts": counts, "decision": decision(violations)}


def draft_mark(lang: str = "tr") -> str:
    """A mark printed on every page of a PDF the text check made a draft; it takes no room in the page's flow."""
    word = "TASLAK · Kontrol raporu engelleyici bulgu buldu" if lang == "tr" else "DRAFT · the text check found a blocking problem"
    return ('<div style="position:fixed;top:2mm;right:4mm;z-index:9;color:#a00;font:700 8pt sans-serif;'
            f'letter-spacing:.04em">{word}</div>')


SHEET_NAME = {"tr": "Kontrol raporu", "en": "Text check"}


def sheet(record: dict | None, lang: str = "tr") -> dict:
    """The "Kontrol raporu" sheet of the appendix."""
    rows = sheet_rows(record, lang)
    return {"name": SHEET_NAME["tr" if lang == "tr" else "en"], "header": rows[0], "rows": rows[1:],
            "widths": [8, 34, 12, 6, 28, 70, 70]}


def sheet_rows(record: dict | None, lang: str = "tr") -> list[list]:
    """The "Kontrol raporu" sheet's rows (header first). No record: the check could not run, said so."""
    tr = lang == "tr"
    header = (["Kural", "Kontrol", "Engelleyici mi", "Kart", "Nerede", "Ne bulundu", "Metin"] if tr else
              ["Rule", "Check", "Blocking", "Card", "Where", "Found", "Text"])
    if not record:
        return [header, ["—", "Kontrol çalışmadı: ekip raporunun kartları kurulamadı" if tr else
                         "Not run: the team report's cards could not be built", "", "", "", "", ""]]
    names = RULE_NAMES["tr" if tr else "en"]
    decision_word = {"PASS": "Geçti" if tr else "Passed", "CONDITIONAL": "Uyarılı" if tr else "Conditional",
                     "BLOCKED": "Taslak (engelleyici bulgu var)" if tr else "Draft (blocking finding)"}[record["decision"]]
    rows = [header, ["Sonuç" if tr else "Result", decision_word, record.get("hard", 0), "", "",
                     f"{len(record['violations'])} bulgu" if tr else f"{len(record['violations'])} findings", ""]]
    for v in record["violations"]:
        rows.append([v["rule"], names.get(v["rule"], v["rule"]), ("Evet" if tr else "Yes") if v["hard"] else ("Hayır" if tr else "No"),
                     v.get("card") or "", v.get("where") or "", v["message"], v.get("text") or ""])
    if record.get("llm"):
        rows.append(["LLM", names["LLM"], "Hayır" if tr else "No", "", "", record["llm"].get("note") or "", ""])
    for s in record.get("suggestions") or []:
        rows.append(["LLM", names["LLM"], "Hayır" if tr else "No", s.get("card") or "", s.get("where") or "",
                     s.get("problem") or "", s.get("text") or ""])
    if len(rows) == 2 + (1 if record.get("llm") else 0) and not record["violations"] and not record.get("suggestions"):
        rows.append(["", "Sorun bulunmadı" if tr else "Nothing found", "", "", "", "", ""])
    return rows
