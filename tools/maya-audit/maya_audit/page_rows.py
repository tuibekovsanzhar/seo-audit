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
           "ids": "ölçüm kimlikleri: {v}", "types": "beklenen tür: {a}; bulunan: {b}", "clash": "aynı öğe için türler: {v}",
           "title_m": "başlık \"{v}\" ({n} karakter)", "desc_m": "açıklama {n} karakter: \"{v}\"", "no_desc": "açıklama yok",
           "lang_m": "<html lang> {v}", "no_lang": "<html lang> yok", "schema_m": "yapısal veri: {v}", "no_schema": "yapısal veri yok",
           "cache_m": "önbellek: {v}", "main_chars": "ana içerik {n} karakter", "h1_none": "ana başlık (h1) yok",
           "no_jumps": "atlanan başlık düzeyi yok", "jumps_m": "{n} başlık düzeyi atlaması ({v})", "alt_missing": "{n} görselin alt metni yok",
           "images_m": "{n} görsel", "dead": "{n} adressiz bağlantı", "controls": "{n} düğme gibi kullanılan bağlantı",
           "hreflang_m": "{n} hreflang etiketi", "no_tags": "ölçüm etiketi yok",
           "not_read": "okunmadı: bu adresin içeriği ölçülmedi", "yes": "Evet", "no": "Hayır, okunmadı", "na": "—",
           # DECISIONS 324: the field a finding is about, when it has no value of its own on the page
           "no_crumb": "breadcrumb yok; içerikte kategori bağlantısı yok", "bots_blocked": "engellenen botlar: {v}",
           "ua_pair": "tarayıcı {a}, {bot} {b}", "two_values": "{field}: {v}", "names": "marka adı: {v}"},
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
           "ids": "measurement IDs: {v}", "types": "expected type: {a}; found: {b}", "clash": "types for one item: {v}",
           "title_m": "title \"{v}\" ({n} characters)", "desc_m": "description {n} characters: \"{v}\"", "no_desc": "no description",
           "lang_m": "<html lang> {v}", "no_lang": "no <html lang>", "schema_m": "structured data: {v}", "no_schema": "no structured data",
           "cache_m": "cache: {v}", "main_chars": "main content {n} characters", "h1_none": "no main heading (h1)",
           "no_jumps": "no skipped heading level", "jumps_m": "{n} heading level jump(s) ({v})", "alt_missing": "{n} image(s) without alt text",
           "images_m": "{n} image(s)", "dead": "{n} link(s) without an address", "controls": "{n} link(s) used as buttons",
           "hreflang_m": "{n} hreflang tag(s)", "no_tags": "no measurement tag",
           "not_read": "not read: this address's content was not measured", "yes": "Yes", "no": "No, not read", "na": "—",
           "no_crumb": "no breadcrumb; no category link in the content", "bots_blocked": "blocked bots: {v}",
           "ua_pair": "browser {a}, {bot} {b}", "two_values": "{field}: {v}", "names": "brand name: {v}"},
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


def from_page(finding: dict, rec: dict, lang: str = "tr") -> list[str]:
    """DECISIONS 323: the values of this finding's kind, from what was measured on the page (`page_measures`): HTML
    size and where the main content starts, headings, title and description, canonical, language, words, first
    response and cache, images, scripts, tags, structured data, status. Only values the record holds."""
    W, ev = WORDS[lang], finding.get("evidence") or {}
    rule, check = str(finding.get("rule_id") or ""), str(finding.get("check_id") or "")
    out: list[str] = []

    def size():
        if isinstance(rec.get("html_bytes"), int):
            out.append(W["html"].format(n=_kb(rec["html_bytes"], lang)))

    def start():
        if isinstance(rec.get("main_offset_bytes"), int):
            out.append(W["main_offset"].format(n=_kb(rec["main_offset_bytes"], lang)))

    def jumps():
        if isinstance(rec.get("heading_jumps"), int):
            out.append(W["jumps_m"].format(n=rec["heading_jumps"], v=", ".join(rec.get("heading_jump_examples") or []))
                       if rec["heading_jumps"] else W["no_jumps"])

    def title_():
        if isinstance(rec.get("title"), str):
            out.append(W["title_m"].format(v=_short(rec["title"], 70), n=rec.get("title_chars", len(rec["title"]))))

    def desc():
        if isinstance(rec.get("description"), str):
            out.append(W["desc_m"].format(n=rec.get("description_chars", len(rec["description"])), v=_short(rec["description"], 60)))
        elif "title" in rec:
            out.append(W["no_desc"])

    def canonical():
        if rec.get("canonical"):
            out.append(W["canonical"].format(u=rec["canonical"]))

    def lang_():
        out.append(W["lang_m"].format(v=rec["html_lang"]) if rec.get("html_lang") else W["no_lang"])
        if rec.get("hreflang"):
            out.append(W["hreflang_m"].format(n=rec["hreflang"]))

    def words():
        if isinstance(rec.get("words"), int):
            out.append(W["words"].format(n=rec["words"]))

    def status():
        if isinstance(rec.get("status"), int):
            out.append(W["status"].format(n=rec["status"]))

    if check == "RND-6":
        (start if "late" in rule else size)()
        if out and isinstance(ev.get("threshold_bytes"), (int, float)):
            out.append(W["threshold"].format(n=_kb(ev["threshold_bytes"], lang)))
    elif "heading" in rule:
        jumps()
    elif rule.startswith("tseo1.title") or check == "STR-1":
        title_()
    elif rule.startswith("tseo1.description") or check == "STR-16":
        desc()
    elif rule.startswith("tseo1.blocking"):
        if isinstance(rec.get("blocking_scripts"), int):
            out.append(W["scripts"].format(n=rec["blocking_scripts"]))
    elif rule.startswith("tseo1.analytics"):
        out.append(W["ids"].format(v=", ".join(rec["analytics"])) if rec.get("analytics") else W["no_tags"])
    elif check == "STR-2":
        if isinstance(rec.get("h1_count"), int):
            out.append(W["h1"].format(n=rec["h1_count"]) if rec["h1_count"] else W["h1_none"])
    elif check in ("STR-12", "STR-9"):
        lang_()
        words()
    elif check in ("STR-15", "RND-3", "RND-7"):
        words()
        if isinstance(rec.get("main_chars"), int):
            out.append(W["main_chars"].format(n=rec["main_chars"]))
    elif check == "STR-7":
        if isinstance(rec.get("images"), int):
            out.append(W["images_m"].format(n=rec["images"]))
        if rec.get("images_missing_alt"):
            out.append(W["alt_missing"].format(n=rec["images_missing_alt"]))
    elif check in ("STR-3", "STR-6", "STR-10"):
        out.append(W["schema_m"].format(v=", ".join(rec["schema_types"])) if rec.get("schema_types") else W["no_schema"])
    elif check in ("IDX-3", "IDX-4", "IDX-6", "IDX-8"):
        canonical()
        status()
    elif check == "PRF-1":
        if isinstance(rec.get("ttfb_ms"), (int, float)):
            out.append(W["ttfb"].format(n=round(rec["ttfb_ms"])))
        if rec.get("cache"):
            out.append(W["cache_m"].format(v=rec["cache"]))
    elif check in ("STR-14", "STR-19") or rule.startswith("shared.link"):
        if rec.get("dead_link_total"):
            out.append(W["dead"].format(n=rec["dead_link_total"]))
        if rec.get("link_control_total"):
            out.append(W["controls"].format(n=rec["link_control_total"]))
    elif check == "IDX-1":
        status()  # the status is what IDX-1 is about
    # DECISIONS 324: no generic fallback (the page's status and size said nothing about most findings): the caller
    # gives the field the finding is about (`about`) or "—".
    return out


def about(finding: dict, url: str, lang: str = "tr") -> list[str]:
    """DECISIONS 324: the field a finding is about, from its own evidence, when the page holds no value of its kind:
    the category link of IDX-7, the bots each AI-access finding names, the two user agents' answers of ACC-4, the field
    and its two values of STR-11, the brand names of STR-5."""
    W, ev = WORDS[lang], finding.get("evidence") or {}
    rule, check = str(finding.get("rule_id") or ""), str(finding.get("check_id") or "")
    if rule == "idx7.product_no_category":
        return [W["no_crumb"]]
    if check == "ACC-6" and ev.get("blocked_tokens"):
        return [W["bots_blocked"].format(v=", ".join(map(str, ev["blocked_tokens"][:6])))]
    if check == "ACC-4":
        for pair in ev.get("pairs") or []:
            if isinstance(pair, dict) and _same(pair.get("url"), url):
                bot = next((k for k in pair if k not in ("url", "outcome", "notes", "browser") and isinstance(pair[k], dict)), None)
                a = (pair.get("browser") or {}).get("status")
                b = (pair.get(bot) or {}).get("status") if bot else None
                if a is not None and b is not None:
                    return [W["ua_pair"].format(a=a, bot=str(bot).capitalize() if bot != "googlebot" else "Googlebot", b=b)]
    if check == "STR-11":
        out = []
        for c in ev.get("contradictions") or []:
            if isinstance(c, dict) and _same(c.get("url"), url) and c.get("field"):
                values = [", ".join(map(str, d.get("value") or [])) for d in c.get("descriptions") or [] if isinstance(d, dict)]
                out.append(W["two_values"].format(field=c["field"], v=" / ".join(v for v in values if v)))
        return out
    if check == "STR-5":
        variants = [v for v in ev.get("variants") or [] if isinstance(v, dict) and v.get("name")]
        here = [v["name"] for v in variants if any(isinstance(s, dict) and _same(s.get("url"), url) for s in v.get("seen_as") or [])]
        names = here or [v["name"] for v in sorted(variants, key=lambda v: -(v.get("pages") or 0))]
        return [W["names"].format(v=", ".join(dict.fromkeys(names[:3])))] if names else []
    return []


def measured(finding: dict, url: str, lang: str = "tr", page: dict | None = None, read: bool | None = None) -> str:
    """What was measured on this page for this finding, in plain words: the finding's own evidence for this page
    first (it holds values only the check works out, e.g. a language share), then what was measured on the page
    (`page`, a `page_measures` record, DECISIONS 323). An address that was not read says so; a page read whose values
    were not kept says "not kept" — never empty, zero or made up."""
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
    if not found and page:
        found = from_page(finding, page, lang)
    if not found:
        found = about(finding, url, lang)
    if not found and any(isinstance(v, list) and any(isinstance(u, str) and _same(u, url) for u in v)
                         for k, v in ev.items() if k not in SKIP_KEYS and k != "urls"):
        found = [W["seen"]]  # the page is in the evidence's list; the finding itself is what was measured there
    if not found and page:
        return W["na"]  # DECISIONS 324: a page read with no value of this kind: "—", never its generic status and size
    if not found and read is False:
        return W["not_read"]
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
                          "p_level": t.get("p_level"),
                          "finding_ids": list(t.get("finding_ids") or [])})
            for fid in t.get("finding_ids") or []:
                by_id.setdefault(fid, t.get("n"))
    else:
        for g in selection.get("cards") or []:
            merged = merge_group(g["lead"]) if g.get("lead") else None
            name = ((merged["title"].get(lang) or merged["title"]["en"]) if merged else
                    (title(g.get("check_id"), g.get("title") or "") if title else None) or g.get("title"))
            cards.append({"n": g.get("card"), "title": name, "severity": g.get("severity"),
                          "issue_type": g.get("issue_type"), "p_level": (g.get("p_level") or {}).get("level"),
                          "finding_ids": list(g["finding_ids"])})
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
    read_urls = {u.rstrip("/") for u in selection.get("_pages_read") or ()}
    measures = {u.rstrip("/"): r for u, r in (selection.get("_page_measures") or {}).items()}
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
                # DECISIONS 323: read or not; a host's file or the whole site is not a page (None)
                read = None if hosts or not url else url.rstrip("/") in read_urls
                rows.append({
                    "finding_id": m.get("id"), "check_id": m.get("check_id"), "rule_id": m.get("rule_id"),
                    "title": name, "short": short, "fix": todo, "severity": sev, "issue_type": g.get("issue_type") or "issue",
                    "placement": g.get("placement"), "card": by_id.get(m.get("id")),
                    "url": url, "address": display_address(url, hosts) if url else W["site"],
                    "host_level": bool(hosts), "page": bool(url) and not hosts,
                    "page_type": rec.get("page_type"), "importance": rec.get("importance"),
                    "value": measured(m, url, lang, measures.get(url.rstrip("/")) if read else None, read) if url else "",
                    "read": read,
                    "_group": gi,
                })
    # DECISIONS 338: a card the team report puts together from Info notes ("Küçük ... tutarsızlıkları", "Soru
    # başlıklarını düzeltin") names checks, not findings: each of its addresses is a row of its own, with what was
    # seen there, so no card is without its pages.
    real = {r["finding_id"] for r in rows}
    for t in todos or []:
        if any(fid in real for fid in t.get("finding_ids") or []):
            continue
        notes = t.get("url_notes") or {}
        for url in t.get("all_urls") or []:
            rec = importance.get(url) or {}
            read = url.rstrip("/") in read_urls
            rows.append({"finding_id": " · ".join(t.get("finding_ids") or []), "check_id": None, "rule_id": None,
                         "title": t.get("title") or "", "short": t.get("title") or "", "fix": (t.get("steps") or "").split("\n")[0],
                         "severity": t.get("severity") or "Info", "issue_type": "issue", "placement": "note", "card": t.get("n"),
                         "url": url, "address": display_address(url, None), "host_level": False, "page": True,
                         "page_type": rec.get("page_type"), "importance": rec.get("importance"), "value": notes.get(url, ""),
                         "read": read, "_group": 10_000 + (t.get("n") or 0)})
    order = {s: i for i, s in enumerate(SEVERITIES)}
    # DECISIONS 323: within each card (and among the rows of no card), the pages read first, the addresses never read
    # after them, grouped; then severity, the finding, the more important page.
    rows.sort(key=lambda r: (r["card"] is None, r["card"] or 0, r["read"] is False, order.get(r["severity"], 9), r["_group"],
                             -(r["importance"] if isinstance(r["importance"], (int, float)) else -1)))
    return rows


def read_word(read: bool | None, lang: str) -> str:
    """"Evet" / "Hayır, okunmadı" ("Yes" / "No, not read"); "—" for a host's file or the whole site."""
    W = WORDS[lang]
    return W["na"] if read is None else W["yes"] if read else W["no"]


def page_table(rows: list[dict]) -> list[dict]:
    """One row per affected page with at least one problem (Blocker to Low): its type and importance, how many
    problems (root-cause groups) concern it, the worst severity, and their short names. Hosts and "whole site" rows
    are not pages and stay in the per-finding rows. The pages read first, by importance (not computed last), then
    severity; the addresses never read after them (DECISIONS 323)."""
    pages: dict[str, dict] = {}
    for r in rows:
        if not r["page"] or r["severity"] not in PROBLEM:
            continue
        p = pages.setdefault(r["url"], {"url": r["url"], "page_type": r["page_type"], "importance": r["importance"],
                                        "groups": {}, "cards": [], "worst": r["severity"], "read": r["read"]})
        p["groups"].setdefault(r["_group"], (r["severity"], r["short"]))
        if r["card"] is not None and r["card"] not in p["cards"]:
            p["cards"].append(r["card"])
        if SEVERITIES.index(r["severity"]) < SEVERITIES.index(p["worst"]):
            p["worst"] = r["severity"]
    out = []
    for p in pages.values():
        names = [name for _, name in sorted(p["groups"].values(), key=lambda x: SEVERITIES.index(x[0]))]
        out.append({"url": p["url"], "page_type": p["page_type"], "importance": p["importance"], "read": p["read"],
                    "problems": len(p["groups"]), "worst": p["worst"], "names": list(dict.fromkeys(names)),
                    "cards": sorted(p["cards"])})
    # DECISIONS 323: the pages read first (by importance, then severity), the addresses never read after them.
    out.sort(key=lambda p: (p["read"] is False, not isinstance(p["importance"], (int, float)), -(p["importance"] or 0),
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
                                   "importance": r["importance"], "read": r["read"], "values": [], "finding_ids": []})
        if r["value"] and r["value"] not in row["values"]:
            row["values"].append(r["value"])
        if r["finding_id"] not in row["finding_ids"]:
            row["finding_ids"].append(r["finding_id"])
    result = list(out.values())
    result.sort(key=lambda p: (p["read"] is False, not isinstance(p["importance"], (int, float)), -(p["importance"] or 0)))
    return result
