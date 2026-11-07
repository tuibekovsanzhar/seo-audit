"""Problems by page, for people who are not technical (DECISIONS 322): one row per finding and affected page, with the
value measured on that page, and one row per affected page with its problems.

Built from `client_selection.select` (the same groups, placements and page importance the team report uses) and,
when the caller has them, the team report's cards (`todos`), so a row names the PDF's card number. Used by the XLSX
appendix ("Bulgu bazında", "Sayfa bazında", the summary sheet) and by the web app's "Etkilenen sayfalar" list, so the
two show the same rows. Nothing here changes a finding, a severity or a confidence.

A value is read from the finding's own evidence, for that page only; the evidence keeps a sample of pages (often the
first 40), so a page outside the sample says that its detail was not kept, never a made-up or zero value.
"""
from __future__ import annotations

from typing import Callable
from urllib.parse import urlsplit

from .client_selection import PROBLEM, affected, host_level, merge_group, severity

SEVERITIES = ("S1", "S2", "S3", "S4", "Info")
# Findings that are not the site's problems: Maya's own limits and what a manual check rejected.
LEFT_OUT = ("own_limit", "rejected")
SKIP_KEYS = frozenset({"severity_assessment", "judgment", "source", "bot_provenance", "reproduce", "verification",
                       "regions", "reading", "shared_element"})
URL_KEYS = ("url", "source", "sitemap", "page")

WORDS = {
    "tr": {"not_kept": "ayrıntı kaydedilmedi (rapor yalnız örnek sayfaları saklar)",
           "site": "site geneli", "kb": "{n} KB", "html": "HTML {n}", "size": "boyut {n}", "main_offset": "ana içerik {n} sonra başlıyor",
           "threshold": "sınır {n}", "jumps": "{n} başlık düzeyi atlaması", "jump": "h{a} → h{b}",
           "foreign": "içeriğin %{n}'i başka dilde", "declared": "bildirilen dil {a}, içerik {b}",
           "words": "{n} kelime", "words_change": "{a} → {b} kelime", "chars": "{n} karakter", "ttfb": "ilk yanıt {n} ms",
           "links": "{n} bağlantı", "products": "{n} ürün listeleniyor", "canonical": "kanonik adres: {u}",
           "linked_from": "{n} sayfadan bağlantı alıyor", "main_share": "ana içerik payı %{n}", "status": "HTTP {n}",
           "questions": "{n} soru", "h1": "{n} ana başlık (h1)", "similar": "benzerlik %{n}", "fixed": "doğru yazım: {u}",
           "missing": "eksik: {v}", "tabs": "{n} boş sekme", "load_more": "{n} \"daha fazla\" düğmesi",
           "lastmod": "{a} adresin {b} tanesi aynı lastmod tarihini taşıyor", "observed": "{v}",
           "desc_group": "aynı açıklama {n} sayfada: \"{v}\"", "title_group": "aynı başlık {n} sayfada: \"{v}\"",
           "copy_group": "{n} sayfalık kopya grubunda", "cert": "sertifika {date} tarihinde bitiyor; denetimde {n} gün kalmıştı",
           "cert_invalid": "sertifika geçersiz: {v}", "noindex": "noindex yok", "chars_list": "birleşik olmayan harf: {v}",
           "seen": "bu sayfada görüldü (bkz. Sorun)", "params": "bağlantıda izleme parametresi: {v}",
           "redirect_link": "yönlendiren adrese bağlantı: {a} → {b}", "hreflang": "hreflang {a} → {b} (HTTP {n})",
           "alt": "alt metni: \"{v}\"", "scripts": "{n} engelleyen betik", "images": "{n} boyutsuz görsel",
           "ids": "ölçüm kimlikleri: {v}", "types": "beklenen tür: {a}; bulunan: {b}", "clash": "aynı öğe için türler: {v}"},
    "en": {"not_kept": "detail not kept (the report keeps sample pages only)",
           "site": "whole site", "kb": "{n} KB", "html": "HTML {n}", "size": "size {n}", "main_offset": "main content starts after {n}",
           "threshold": "limit {n}", "jumps": "{n} heading level jump(s)", "jump": "h{a} → h{b}",
           "foreign": "{n}% of the content in another language", "declared": "declared {a}, content {b}",
           "words": "{n} words", "words_change": "{a} → {b} words", "chars": "{n} characters", "ttfb": "first response {n} ms",
           "links": "{n} link(s)", "products": "{n} product(s) listed", "canonical": "canonical: {u}",
           "linked_from": "linked from {n} page(s)", "main_share": "main content share {n}%", "status": "HTTP {n}",
           "questions": "{n} question(s)", "h1": "{n} main heading(s) (h1)", "similar": "similarity {n}%", "fixed": "correct spelling: {u}",
           "missing": "missing: {v}", "tabs": "{n} empty tab(s)", "load_more": "{n} \"load more\" button(s)",
           "lastmod": "{b} of {a} addresses carry the same lastmod date", "observed": "{v}",
           "desc_group": "same description on {n} pages: \"{v}\"", "title_group": "same title on {n} pages: \"{v}\"",
           "copy_group": "in a group of {n} copies", "cert": "certificate expires on {date}; {n} days were left at the audit",
           "cert_invalid": "certificate not valid: {v}", "noindex": "no noindex", "chars_list": "decomposed letter: {v}",
           "seen": "seen on this page (see Problem)", "params": "tracking parameter in a link: {v}",
           "redirect_link": "link to a redirecting address: {a} → {b}", "hreflang": "hreflang {a} → {b} (HTTP {n})",
           "alt": "alt text: \"{v}\"", "scripts": "{n} blocking script(s)", "images": "{n} image(s) without size",
           "ids": "measurement IDs: {v}", "types": "expected type: {a}; found: {b}", "clash": "types for one item: {v}"},
}


def _same(a: str, b: str) -> bool:
    return isinstance(a, str) and isinstance(b, str) and a.rstrip("/") == b.rstrip("/")


def display_address(url: str, hosts: list[str] | None = None) -> str:
    """The address as a person reads it: a host-level finding's host root is its plain host name ("airastana.com",
    never "https://airastana.com/"); a page keeps its full address (DECISIONS 322 (7))."""
    if hosts:
        parts = urlsplit(url)
        if parts.hostname and parts.path in ("", "/") and not parts.query:
            return parts.hostname
    return url


def _kb(n, lang: str) -> str:
    value = round(n / 1000)
    text = f"{value:,}".replace(",", "." if lang == "tr" else ",")
    return WORDS[lang]["kb"].format(n=text)


def _pct(x: float) -> str:
    return f"{round(x * 100) if x <= 1 else round(x)}"


def _short(text, limit: int = 70) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _record_words(rec: dict, ev: dict, lang: str, check_id: str | None = None) -> list[str]:
    """The measured values of one page's evidence record, in plain words; keys this does not know are left out."""
    W, out = WORDS[lang], []
    if isinstance(rec.get("bytes"), (int, float)):
        out.append(W["html" if check_id == "RND-6" else "size"].format(n=_kb(rec["bytes"], lang)))
    if isinstance(rec.get("main_offset_bytes"), (int, float)):
        out.append(W["main_offset"].format(n=_kb(rec["main_offset_bytes"], lang)))
    if out and isinstance(ev.get("threshold_bytes"), (int, float)):
        out.append(W["threshold"].format(n=_kb(ev["threshold_bytes"], lang)))
    if isinstance(rec.get("jump_count"), int):
        out.append(W["jumps"].format(n=rec["jump_count"]))
    if isinstance(rec.get("from"), int) and isinstance(rec.get("to"), int):
        out.append(W["jump"].format(a=rec["from"], b=rec["to"]))
    if rec.get("declared") and (rec.get("main_content_language") or rec.get("detected")):
        out.append(W["declared"].format(a=rec["declared"], b=rec.get("main_content_language") or rec.get("detected")))
    if isinstance(rec.get("foreign_share"), (int, float)):
        out.append(W["foreign"].format(n=_pct(rec["foreign_share"])))
    if isinstance(rec.get("words_before"), int) and isinstance(rec.get("words_after"), int):
        out.append(W["words_change"].format(a=rec["words_before"], b=rec["words_after"]))
    for key in ("main_content_words", "main_words"):
        if isinstance(rec.get(key), int) and not rec.get("declared"):
            out.append(W["words"].format(n=rec[key]))
    if isinstance(rec.get("characters"), int):
        out.append(W["chars"].format(n=rec["characters"]))
    elif isinstance(rec.get("characters"), list) and rec["characters"]:
        out.append(W["chars_list"].format(v=", ".join(str(c) for c in rec["characters"][:3])))
    if isinstance(rec.get("ttfb_ms"), (int, float)):
        out.append(W["ttfb"].format(n=round(rec["ttfb_ms"])))
    if isinstance(rec.get("links"), int):
        out.append(W["links"].format(n=rec["links"]))
    if isinstance(rec.get("products_listed"), int):
        out.append(W["products"].format(n=rec["products_listed"]))
    if isinstance(rec.get("linked_from_pages"), int):
        out.append(W["linked_from"].format(n=rec["linked_from_pages"]))
    if isinstance(rec.get("canonical"), str) and rec["canonical"]:
        out.append(W["canonical"].format(u=rec["canonical"]))
    if isinstance(rec.get("main_share"), (int, float)):
        out.append(W["main_share"].format(n=_pct(rec["main_share"])))
    if isinstance(rec.get("questions"), int):
        out.append(W["questions"].format(n=rec["questions"]))
    if isinstance(rec.get("h1"), list) and rec["h1"]:
        out.append(W["h1"].format(n=len(rec["h1"])))
    elif isinstance(rec.get("raw_h1"), list):
        out.append(W["h1"].format(n=len(rec["raw_h1"])))
    if isinstance(rec.get("value"), float) and rec.get("comparison"):
        out.append(W["similar"].format(n=_pct(rec["value"])))
    if isinstance(rec.get("fixed"), str) and rec["fixed"]:
        out.append(W["fixed"].format(u=rec["fixed"]))
    if isinstance(rec.get("missing"), list) and rec["missing"]:
        out.append(W["missing"].format(v=", ".join(str(m) for m in rec["missing"][:4])))
    if isinstance(rec.get("empty_tabpanels"), list) and rec["empty_tabpanels"]:
        out.append(W["tabs"].format(n=len(rec["empty_tabpanels"])))
    if isinstance(rec.get("load_more_buttons"), list) and rec["load_more_buttons"]:
        out.append(W["load_more"].format(n=len(rec["load_more_buttons"])))
    if isinstance(rec.get("urls"), int) and isinstance(rec.get("same_lastmod"), int):
        out.append(W["lastmod"].format(a=rec["urls"], b=rec["same_lastmod"]))
    if isinstance(rec.get("parameters"), list) and rec["parameters"] and rec.get("target"):
        out.append(W["params"].format(v=", ".join(str(p) for p in rec["parameters"][:3])))
    if rec.get("hreflang") and rec.get("target") and isinstance(rec.get("status"), int):
        out.append(W["hreflang"].format(a=rec["hreflang"], b=rec["target"], n=rec["status"]))
    if isinstance(rec.get("alt"), str) and rec.get("src"):
        out.append(W["alt"].format(v=_short(rec["alt"], 50)))
    if isinstance(rec.get("scripts"), int):
        out.append(W["scripts"].format(n=rec["scripts"]))
    if isinstance(rec.get("images"), int):
        out.append(W["images"].format(n=rec["images"]))
    tags = [str(m) for m in (rec.get("containers") or []) + (rec.get("measurement_ids") or []) if m]
    if tags and isinstance(rec.get("measurement_ids"), list):
        out.append(W["ids"].format(v=", ".join(list(dict.fromkeys(tags))[:4])))
    if isinstance(rec.get("field"), str) and isinstance(rec.get("value"), str):
        out.append(f'{rec["field"]}: {_short(rec["value"], 60)}')
    if isinstance(rec.get("expected_one_of"), list) and rec["expected_one_of"]:
        out.append(W["types"].format(a=" / ".join(map(str, rec["expected_one_of"][:3])),
                                     b=", ".join(map(str, rec.get("types_found") or [])) or "—"))
    if rec.get("noindex") is False:
        out.append(W["noindex"])
    if isinstance(rec.get("status"), int) and not out:
        out.append(W["status"].format(n=rec["status"]))
    if not out and lang == "en" and isinstance(rec.get("observed"), str):
        out.append(W["observed"].format(v=_short(rec["observed"], 120)))
    return out


def _decomposed(url: str, lang: str) -> str | None:
    """TSEO-1's decomposed letters, read from the address itself (no sample needed), with the engine's own rule for
    the address written with composed letters (`checks.quick_rules`)."""
    import unicodedata
    from urllib.parse import quote, unquote
    from .checks.quick_rules import composed
    path = unquote(urlsplit(url).path)
    marks = sorted({f"U+{ord(ch):04X}" for ch in path if unicodedata.combining(ch)})
    if not marks:
        return None
    fixed = urlsplit(url)._replace(path=quote(composed(path), safe="/:@!$&'()*+,;=-._~")).geturl()
    W = WORDS[lang]
    return W["chars_list"].format(v=", ".join(marks)) + "; " + W["fixed"].format(u=fixed)


def measured(finding: dict, url: str, lang: str = "tr") -> str:
    """What was measured on this page for this finding, in plain words, from the finding's evidence; the "not kept"
    sentence when the evidence holds no record of this page."""
    W, ev = WORDS[lang], finding.get("evidence") or {}
    if finding.get("rule_id") == "tseo1.url_decomposed":
        found_in_address = _decomposed(url, lang)
        if found_in_address:
            return found_in_address
    hosts = host_level(finding)
    if finding.get("check_id") == "IDX-2" and hosts:
        host = urlsplit(url).hostname
        for h in ev.get("hosts") or []:
            if not isinstance(h, dict) or h.get("host") != host:
                continue
            if h.get("valid") is False:
                return W["cert_invalid"].format(v=h.get("verify_message") or h.get("error") or "—")
            if h.get("not_after") and isinstance(h.get("days_left"), (int, float)):
                return W["cert"].format(date=str(h["not_after"])[:10], n=int(h["days_left"]))
    found: list[str] = []
    for key, value in ev.items():
        if key in SKIP_KEYS or not isinstance(value, list):
            continue
        for rec in value:
            if not isinstance(rec, dict):
                continue
            if any(_same(rec.get(k), url) for k in URL_KEYS):
                found += [w for w in _record_words(rec, ev, lang, finding.get("check_id")) if w not in found]
            elif isinstance(rec.get("linked_from"), list) and any(_same(u, url) for u in rec["linked_from"]) and rec.get("url"):
                found.append(W["redirect_link"].format(a=rec["url"], b=rec.get("final") or "?"))
            elif isinstance(rec.get("on_pages"), list) and any(_same(u, url) for u in rec["on_pages"]) and rec.get("types"):
                found.append(W["clash"].format(v=", ".join(map(str, rec["types"][:4]))))
            elif isinstance(rec.get("urls"), list) and any(_same(u, url) for u in rec["urls"]):
                n = len(rec["urls"])
                if rec.get("description"):
                    found.append(W["desc_group"].format(n=rec.get("count") or n, v=_short(rec["description"], 60)))
                elif rec.get("title"):
                    found.append(W["title_group"].format(n=n, v=_short(rec["title"], 60)))
                else:
                    found.append(W["copy_group"].format(n=n))
    if not found and isinstance(ev.get("url"), str) and _same(ev["url"], url):
        found = _record_words(ev, ev, lang, finding.get("check_id"))
    if not found and any(isinstance(v, list) and any(isinstance(u, str) and _same(u, url) for u in v)
                         for k, v in ev.items() if k not in SKIP_KEYS and k != "urls"):
        found = [W["seen"]]  # the page is in the evidence's list; the finding itself is what was measured there
    return "; ".join(found[:4]) if found else W["not_kept"]


# ---------------------------------------------------------------------------------------------------- the rows

def card_of(selection: dict, todos: list[dict] | None = None, lang: str = "tr",
            title: Callable[[str, str], str] | None = None) -> tuple[dict[str, int], list[dict]]:
    """({finding id: card number}, cards) — the PDF's cards when the team report's `todos` are given (their numbers,
    titles, owners), else the selection's cards. A note card that names checks ("STR-2 · STR-9") is about the checks'
    observations, not findings: no finding row is given its number."""
    by_id: dict[str, int] = {}
    cards: list[dict] = []
    if todos:
        for t in todos:
            cards.append({"n": t.get("n"), "title": t.get("title"), "addresses": len(t.get("all_urls") or []), "severity": t.get("severity"),
                          "severity_label": t.get("severity_label"), "issue_type": t.get("issue_type"),
                          "issue_type_label": t.get("issue_type_label"), "owner": t.get("owner"), "effort": t.get("effort"),
                          "finding_ids": list(t.get("finding_ids") or [])})
            for fid in t.get("finding_ids") or []:
                by_id.setdefault(fid, t.get("n"))
    else:
        for g in selection.get("cards") or []:
            merged = merge_group(g["lead"]) if g.get("lead") else None
            name = ((merged["title"].get(lang) or merged["title"]["en"]) if merged else
                    (title(g.get("check_id"), g.get("title") or "") if title else None) or g.get("title"))
            cards.append({"n": g.get("card"), "title": name, "severity": g.get("severity"),
                          "issue_type": g.get("issue_type"), "finding_ids": list(g["finding_ids"])})
            for fid in g["finding_ids"]:
                by_id.setdefault(fid, g.get("card"))
    return by_id, cards


def finding_rows(selection: dict, lists: dict | None = None, lang: str = "tr", *, todos: list[dict] | None = None,
                 words: Callable[[dict], dict | None] | None = None, title: Callable[[str, str], str] | None = None,
                 fix: Callable[[str], str] | None = None) -> list[dict]:
    """One row per finding and affected page (a finding with no address: one "whole site" row), every finding of the
    report except Maya's own limits and rejected ones. `words(finding)` gives the plain problem name and fix (the
    team report's text library: {"finding", "summary", "explanation"}) or None; else the worded engine title and fix.
    Order: the PDF's cards in their order, then by severity, then the more important page first."""
    W = WORDS[lang]
    importance = selection.get("_importance") or {}
    by_id, _ = card_of(selection, todos, lang, title)
    rows = []
    for gi, g in enumerate(selection.get("groups") or []):
        if g.get("placement") in LEFT_OUT:
            continue
        for m in g["members"]:
            entry = words(m) if words else None
            name = (entry or {}).get("finding") or (title(m.get("check_id"), m.get("title") or "") if title else None) or m.get("title") or ""
            short = (entry or {}).get("summary") or name
            todo = (entry or {}).get("explanation") or ((fix(m.get("how_to_fix")) if fix and m.get("how_to_fix") else None)
                                                         or m.get("how_to_fix") or "")
            hosts = host_level(m)
            urls = affected(m, lists) or [None]
            sev = severity(m)
            for url in urls:
                rec = importance.get(url) or {} if url else {}
                rows.append({
                    "finding_id": m.get("id"), "check_id": m.get("check_id"), "rule_id": m.get("rule_id"),
                    "title": name, "short": short, "fix": todo, "severity": sev, "issue_type": g.get("issue_type") or "issue",
                    "placement": g.get("placement"), "card": by_id.get(m.get("id")),
                    "url": url, "address": display_address(url, hosts) if url else W["site"],
                    "host_level": bool(hosts), "page": bool(url) and not hosts,
                    "page_type": rec.get("page_type"), "importance": rec.get("importance"),
                    "value": measured(m, url, lang) if url else "",
                    "_group": gi,
                })
    order = {s: i for i, s in enumerate(SEVERITIES)}
    rows.sort(key=lambda r: (r["card"] is None, r["card"] or 0, order.get(r["severity"], 9), r["_group"],
                             -(r["importance"] if isinstance(r["importance"], (int, float)) else -1)))
    return rows


def page_table(rows: list[dict]) -> list[dict]:
    """One row per affected page with at least one problem (Blocker to Low): its type and importance, how many
    problems (root-cause groups) concern it, the worst severity, and their short names. Hosts and "whole site" rows
    are not pages and stay in the per-finding rows. Sorted by importance (not computed last), then severity."""
    pages: dict[str, dict] = {}
    for r in rows:
        if not r["page"] or r["severity"] not in PROBLEM:
            continue
        p = pages.setdefault(r["url"], {"url": r["url"], "page_type": r["page_type"], "importance": r["importance"],
                                        "groups": {}, "cards": [], "worst": r["severity"]})
        p["groups"].setdefault(r["_group"], (r["severity"], r["short"]))
        if r["card"] is not None and r["card"] not in p["cards"]:
            p["cards"].append(r["card"])
        if SEVERITIES.index(r["severity"]) < SEVERITIES.index(p["worst"]):
            p["worst"] = r["severity"]
    out = []
    for p in pages.values():
        names = [name for _, name in sorted(p["groups"].values(), key=lambda x: SEVERITIES.index(x[0]))]
        out.append({"url": p["url"], "page_type": p["page_type"], "importance": p["importance"],
                    "problems": len(p["groups"]), "worst": p["worst"], "names": list(dict.fromkeys(names)),
                    "cards": sorted(p["cards"])})
    out.sort(key=lambda p: (not isinstance(p["importance"], (int, float)), -(p["importance"] or 0),
                            SEVERITIES.index(p["worst"]), -p["problems"], p["url"]))
    return out


def card_pages(rows: list[dict], n: int) -> list[dict]:
    """The affected addresses of one card (the web app's "Etkilenen sayfalar"): one row per address, its values
    joined when several of the card's findings measured it; the more important page first."""
    out: dict[str, dict] = {}
    for r in rows:
        if r["card"] != n:
            continue
        key = r["url"] or r["address"]
        row = out.setdefault(key, {"url": r["url"], "address": r["address"], "page_type": r["page_type"],
                                   "importance": r["importance"], "values": [], "finding_ids": []})
        if r["value"] and r["value"] not in row["values"]:
            row["values"].append(r["value"])
        if r["finding_id"] not in row["finding_ids"]:
            row["finding_ids"].append(r["finding_id"])
    result = list(out.values())
    result.sort(key=lambda p: (not isinstance(p["importance"], (int, float)), -(p["importance"] or 0)))
    return result
