"""The client report's appendix: every finding and every affected address, as one XLSX (DECISIONS 300 (4)).

Built from `client_selection.select`, so it lists exactly the groups and placements the PDF used. The release gate
(RG-17) checks that it holds every finding of the report. A column with nothing in any row is left out (DECISIONS 300
(7): no empty evidence columns). Turkish or English headers; finding titles and fixes are the engine's, or worded by
the caller (`title`, `fix`: callables taking (check_id, text) and (text,), returning text).
"""
from __future__ import annotations

from typing import Callable

from . import xlsx
from .client_selection import CONFIDENCE_WEIGHT, SEVERITY_NAME, SEVERITY_WEIGHT, appendix_rows

WORDS = {
    "tr": {"findings": "Bulgular", "urls": "Etkilenen adresler", "key_pages": "Kilit sayfalar", "coverage": "Kapsam",
           "method_sheet": "Yöntem", "note": "Not",
           "key_pages_empty": {"reader_only": "Bu denetimde sayfa önemi hesaplanamadı: Maya'nın tarayıcısı engellendi, sayfalar başka bir okuma yoluyla okundu ve kayıtlı kopyalar sayfalar arası bağlantıları tutmuyor; önem bu bağlantılardan hesaplanır.",
                               "no_pages": "Bu denetimde içeriği okunan sayfa olmadığı için sayfa önemi hesaplanamadı."},
           "templates": "Şablonlar", "itype": {"issue": "Sorun", "warning": "Kontrol edin", "opportunity": "Fırsat"},
           "tpl_cols": ["Şablon", "Tür", "Okunan sayfa", "Sorunlu sayfa", "Sorun grubu", "Kartlar", "En yüksek önem", "Bulgu kimlikleri"],
           "tpl_kinds": {"home": "ana sayfa", "category": "kategori", "product": "ürün", "blog_article": "blog yazısı",
                         "policy": "politika", "utility": "yardımcı sayfa", "other": "diğer"},
           "cols": ["Bulgu kimliği", "Kontrol", "Kural", "Önem", "Sorun türü", "Güven (motor)", "Güven sınıfı", "Öncelik puanı",
                    "Yer", "Kart", "Grubun ilk bulgusu", "Teyit nedeni", "Bulgu", "Ne yapılmalı", "Kapsam (sayı)",
                    "Etkilenen adres sayısı", "Okunan sayfa (erişim)", "Okunmayan adres", "Kök neden grubu", "Elle kontrol"],
           "url_cols": ["Bulgu kimliği", "Yer", "Önem", "Adres"],
           "page_cols": ["Sıra", "Adres", "Sayfa türü", "Önem puanı (0-100)", "Kartlar", "En yüksek önem",
                         "Teyit edilecek bulgu sayısı"],
           "cov_cols": ["Tür", "Açıklama", "Kontroller"], "method_cols": ["Bileşen", "Değer"],
           "placement": {"card": "Kart", "confirm": "Teyit edin", "appendix": "Yalnız ekte", "note": "Not",
                         "own_limit": "Maya'nın sınırı (kapsam)", "rejected": "Elle kontrolde reddedildi"},
           "severity": {"S1": "Engelleyici", "S2": "Yüksek", "S3": "Orta", "S4": "Düşük", "Info": "Bilgi"},
           "manual": {"confirmed": "teyit edildi", "rejected": "reddedildi"},
           "class": {"measured": "Ölçüldü", "estimated": "Tahmini", "inferred": "Çıkarım", "unverified": "Doğrulanmamış kontrol"},
           "reason": {"unverified_check": "kontrol gerçek sitelerde doğrulanmadı", "low_confidence": "düşük güven",
                      "intent": "kasıtlı olabilir", "firecrawl_only": "yalnız Firecrawl kopyasında görüldü", "rendered_html": "işlenmiş HTML (Firecrawl), ham boyutla karşılaştırılamaz",
                      "spoofed_googlebot": "Googlebot kimliğiyle yapılan isteğe 403/429"},
           "kind": {"page_cap": "Sayfa sınırı", "time_budget": "Süre sınırı", "reader": "Okuma yolu",
                    "not_assessed": "Değerlendirilmedi"},
           "page_type": {"home": "ana sayfa", "category": "kategori", "product": "ürün", "blog_article": "blog yazısı",
                         "policy": "politika sayfası", "utility": "yardımcı sayfa (arama, sepet, hesap)", "other": "diğer"},
           "home_languages": "ana sayfa ({n} dil)",
           "importance_unknown": "önem hesaplanamadı ({reason}, bkz. kart #{card})",
           "importance_reasons": {"canonical": "kanonik sorunu", "redirect": "yönlendirme sorunu"},
           "method": [("Önem ağırlığı", "Engelleyici 100, Yüksek 40, Orta 15, Düşük 5, Bilgi 0"),
                      ("Güven ağırlığı", "ölçüldü 1,0 · tahmini 0,6 · çıkarım 0,5 · doğrulanmamış 0,4"),
                      ("Erişim", "1 + ln(1 + etkilenen ve okunan sayfaların önem puanı toplamı / 100), en çok 10; okunmayan adres katılmaz (ayrı sütunda sayılır); adressiz bulgu: ana sayfa"),
                      ("Sıra", "önce önem bandı, sonra bant içinde öncelik puanı"),
                      ("Kök neden grupları", "aynı nedeni ve tek düzeltmeyi paylaşan kurallar tek kart (sütun: Kök neden grubu)"),
                      ("İş önemi", "1,0 (iş türü profilleri gelene kadar)"),
                      ("Öncelik puanı", "önem x güven x erişim x iş önemi; efor gösterilir, puana girmez"),
                      ("Kartlar", "en çok 15: bütün Engelleyici/Yüksek gruplar, sonra bant ve puan sırasıyla")]},
    "en": {"findings": "Findings", "urls": "Affected URLs", "key_pages": "Key pages", "coverage": "Coverage",
           "method_sheet": "Method", "note": "Note",
           "key_pages_empty": {"reader_only": "Page importance could not be worked out for this audit: Maya's crawler was blocked, the pages were read another way, and the saved copies keep no links between pages, which importance is computed from.",
                               "no_pages": "Page importance could not be worked out: no page's content was read in this audit."},
           "templates": "Templates", "itype": {"issue": "Issue", "warning": "Warning", "opportunity": "Opportunity"},
           "tpl_cols": ["Template", "Type", "Pages read", "Pages with problems", "Problem groups", "Cards", "Highest severity", "Finding IDs"],
           "tpl_kinds": {"home": "homepage", "category": "category", "product": "product", "blog_article": "blog article",
                         "policy": "policy", "utility": "utility page", "other": "other"},
           "cols": ["Finding ID", "Check", "Rule", "Severity", "Issue type", "Confidence (engine)", "Confidence class",
                    "Priority score", "Placement", "Card", "Group lead", "Confirm because", "Finding", "What to do",
                    "Scope (count)", "Affected URLs (count)", "Pages read (reach)", "Not read", "Root-cause group", "Manual check"],
           "url_cols": ["Finding ID", "Placement", "Severity", "URL"],
           "page_cols": ["Rank", "URL", "Page type", "Importance (0-100)", "Cards", "Highest severity",
                         "Findings to confirm (count)"],
           "cov_cols": ["Kind", "What", "Checks"], "method_cols": ["Part", "Value"],
           "placement": {"card": "Card", "confirm": "Confirm first", "appendix": "Appendix only", "note": "Note",
                         "own_limit": "Maya's own limit (coverage)", "rejected": "Rejected by manual check"},
           "severity": SEVERITY_NAME,
           "manual": {"confirmed": "confirmed", "rejected": "rejected"},
           "class": {"measured": "Measured", "estimated": "Estimated", "inferred": "Inferred", "unverified": "Unverified check"},
           "reason": {"unverified_check": "check not yet validated on real sites", "low_confidence": "low confidence",
                      "intent": "may be intentional", "firecrawl_only": "seen only in Firecrawl's copy", "rendered_html": "rendered HTML (Firecrawl), not comparable with a raw size",
                      "spoofed_googlebot": "403/429 to a request with Googlebot's user agent"},
           "kind": {"page_cap": "Page cap", "time_budget": "Time budget", "reader": "How pages were read",
                    "not_assessed": "Not assessed"},
           "page_type": {"home": "homepage", "category": "category", "product": "product", "blog_article": "blog article",
                         "policy": "policy page", "utility": "utility page (search, cart, account)", "other": "other"},
           "home_languages": "homepage ({n} languages)",
           "importance_unknown": "importance not computed ({reason}, see card #{card})",
           "importance_reasons": {"canonical": "canonical problem", "redirect": "redirect problem"},
           "method": [("Severity weight", "Blocker 100, High 40, Medium 15, Low 5, Info 0"),
                      ("Confidence weight", "measured 1.0 · estimated 0.6 · inferred 0.5 · unverified 0.4"),
                      ("Reach", "1 + ln(1 + summed importance of the affected pages that were read / 100), at most 10; addresses not read add nothing (counted in their own column); no address: the homepage"),
                      ("Order", "severity band first, then priority score within the band"),
                      ("Root-cause groups", "rules sharing one cause and one fix are one card (column: Root-cause group)"),
                      ("Business relevance", "1.0 (until business-type profiles exist)"),
                      ("Priority score", "severity x confidence x reach x business; effort is shown, not scored"),
                      ("Cards", "at most 15: every Blocker/High group, then by band and score")]},
}


def _drop_empty_columns(header: list[str], rows: list[list]) -> tuple[list[str], list[list]]:
    keep = [i for i in range(len(header)) if any(i < len(r) and r[i] not in (None, "", []) for r in rows)]
    return [header[i] for i in keep], [[r[i] if i < len(r) else "" for i in keep] for r in rows]


def _manual(text: str, W: dict) -> str:
    """The manual check's result word in the appendix's language; who checked and what they saw stay as written."""
    word, sep, rest = text.partition(" · ")
    return f"{W['manual'].get(word, word)}{sep}{rest}" if text else ""


def coverage_text(line: dict, lang: str, label: Callable[[str], str] | None = None,
                  sentence: Callable[[str], str] | None = None, title: Callable[[str, str], str] | None = None) -> str:
    """A coverage line in the report's language (DECISIONS 306): the engine's part and reason through the reader's
    wording (`label`, `sentence`), a reader line's finding title through `title`."""
    W = WORDS[lang]
    kind = line["kind"]
    if kind == "page_cap":
        return (f"Sayfa sınırı {line.get('pages')} sayfa; bilinen ama okunmayan adres: {line.get('not_read')}" if lang == "tr"
                else f"Page cap {line.get('pages')} pages; addresses known but not read: {line.get('not_read')}")
    if kind == "time_budget":
        return (f"Süre sınırı {line.get('seconds')} sn; süre yüzünden atlanan adım: {line.get('cut') or '—'}" if lang == "tr"
                else f"Time budget {line.get('seconds')} s; steps cut by time: {line.get('cut') or '—'}")
    if kind == "reader":
        shown = (title(None, line.get("title") or "") if title else None) or line.get("title")
        return f"{shown} ({', '.join(line.get('finding_ids') or [])})"
    if kind == "not_assessed" and (line.get("part") or line.get("reason")) and (label or sentence):
        part = (label(line.get("part")) if label and line.get("part") else None) or line.get("part") or ""
        reason = (sentence(line.get("reason")) if sentence and line.get("reason") else None) or line.get("reason") or ""
        return f"{part}: {reason}".strip(": ")
    return line.get("text") or W["kind"].get(kind, kind)


def sheets(selection: dict, lang: str = "tr", lists: dict | None = None,
           title: Callable[[str, str], str] | None = None, fix: Callable[[str], str] | None = None,
           label: Callable[[str], str] | None = None, line: Callable[[str], str] | None = None) -> list[dict]:
    W = WORDS[lang]
    rows, urls = [], []
    for r in appendix_rows(selection, lists):
        t = (title(r["check_id"], r["title"]) if title else None) or r["title"]
        x = (fix(r["how_to_fix"]) if fix and r["how_to_fix"] else None) or r["how_to_fix"]
        placement = W["placement"].get(r["placement"], r["placement"])
        rows.append([r["finding_id"], r["check_id"], r["rule_id"], W["severity"].get(r["severity"], r["severity"]),
                     W["itype"].get(r.get("issue_type") or "issue", ""), r["confidence"], W["class"].get(r["confidence_class"], r["confidence_class"]), r["priority"],
                     placement, r["card"], r["group_lead"] if r["group_lead"] != r["finding_id"] else "",
                     W["reason"].get(r["confirm_reason"], r["confirm_reason"]) if r["confirm_reason"] else "",
                     t, x, r["scope_count"], len(r["urls"]), r.get("pages_read"), r.get("not_read"),
                     r.get("merge_group") or "", _manual(r.get("manual") or "", W)])
        for u in r["urls"]:
            urls.append([r["finding_id"], placement, W["severity"].get(r["severity"], r["severity"]), u])
    # DECISIONS 312: the homepage's language versions are one row; the cell lists every address.
    pages = [[p["rank"], "\n".join(p.get("languages") or [p["url"]]),
              W["home_languages"].format(n=len(p["languages"])) if p.get("languages") else W["page_type"].get(p["page_type"], p["page_type"]),
              W["importance_unknown"].format(reason=W["importance_reasons"][p["importance_unknown"]["reason"]],
                                             card=p["importance_unknown"]["card"]) if p.get("importance_unknown") else p["importance"],
              ", ".join(str(c) for c in p["cards"]),
              W["severity"].get(p["worst"], "") if p["worst"] else "", p["confirm"]] for p in selection["key_pages"]]
    if not pages:  # say why, in one line, rather than leave the sheet empty
        pages = [[W["key_pages_empty"][selection.get("key_pages_reason") or "no_pages"]]]
    # Stage 8a (DECISIONS 315): problems per template, every template.
    tpls = [[t["template"], W["tpl_kinds"].get(str(t.get("kind")), str(t.get("kind") or "")), t["pages"], t["pages_with_problems"],
             t["problem_groups"], ", ".join(str(c) for c in t["cards"]), W["severity"].get(t["worst"], "") if t.get("worst") else "",
             ", ".join(t["finding_ids"])] for t in selection.get("templates") or []]
    cov = [[W["kind"].get(row["kind"], row["kind"]), coverage_text(row, lang, label, line, title),
            ", ".join(row.get("checks") or [])] for row in selection["coverage"]["lines"]]
    out = []
    for name, header, body, widths in ((W["findings"], W["cols"], rows, [16, 8, 22, 11, 13, 11, 16, 9, 16, 6, 16, 26, 70, 70, 9, 9, 10, 10, 20, 60]),
                                       (W["urls"], W["url_cols"], urls, [16, 16, 11, 90]),
                                       (W["key_pages"], W["page_cols"], pages, [6, 70, 12, 10, 14, 12, 10]),
                                       (W["templates"], W["tpl_cols"], tpls, [40, 16, 12, 12, 12, 16, 14, 60]),
                                       (W["coverage"], W["cov_cols"], cov, [18, 110, 40]),
                                       (W["method_sheet"], W["method_cols"], [list(m) for m in W["method"]], [22, 100])):
        if name == W["key_pages"] and not selection["key_pages"]:
            out.append({"name": name, "header": [W["note"]], "rows": body, "widths": [140]})
            continue
        h, b = _drop_empty_columns(header, body) if body else (header, body)
        keep = [header.index(c) for c in h]
        out.append({"name": name, "header": h, "rows": b, "widths": [widths[i] for i in keep]})
    return out


def build(selection: dict, lang: str = "tr", lists: dict | None = None, **wording) -> bytes:
    return xlsx.workbook(sheets(selection, lang, lists, **wording))


def finding_ids(data: bytes, lang: str = "tr") -> set[str]:
    """The finding ids an appendix file lists (its first sheet's first column), for RG-17 on the written file."""
    first = next(iter(xlsx.read(data).values()), [])
    return {row[0] for row in first[1:] if row and row[0]}


assert set(SEVERITY_WEIGHT) == set(WORDS["tr"]["severity"]) and set(CONFIDENCE_WEIGHT) == set(WORDS["tr"]["class"])
