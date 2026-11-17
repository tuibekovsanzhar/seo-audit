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

# DECISIONS 322: four sheets for teammates who are not technical come first; the technical sheets follow unchanged.
READ = {
    "tr": {"how": "Nasıl okunur", "summary": "Özet", "by_page": "Sayfa bazında", "by_finding": "Bulgu bazında",
           "lines": ["Bu dosya, denetimde bulunan sorunları sayfa sayfa gösterir; okumak için teknik bilgi gerekmez.",
                     "«Özet»: PDF raporundaki kartlar, aynı sıra ve numarayla. Bir kartın «Satırlara git» bağlantısı, o kartın sayfalarını «Bulgu bazında» sayfasında açar.",
                     "«Sayfa bazında»: sorunlu her sayfa bir satır, en önemli sayfa en üstte. Önem puanı 0-100 arasıdır; boşsa sayfa taranmadığı için hesaplanmadı.",
                     "«Bulgu bazında»: her sorun ve sayfa bir satır: o sayfada ölçülen değer ve ne yapılacağı. Teknik kimlikler en sağdaki sütunlardadır.",
                     "Süzmek için başlık satırındaki ok düğmelerini kullanın (ör. Kart = 3 ya da Önem = Yüksek). Bir adrese tıklayınca sayfa tarayıcıda açılır.",
                     "Önem sırası: Engelleyici, Yüksek, Orta, Düşük, Bilgi. «Bilgi» satırları sorun değil nottur. «Bulgular» ve sonraki sayfalar ekibin teknik ayrıntılarıdır.",
                     "«Okundu mu?»: «Evet» içeriği okunup ölçülen sayfa, «Hayır, okunmadı» bilinen ama okunmayan adrestir; okunan sayfalar önce, okunmayan adresler ayrı bir grup olarak sonra gelir.",
                     "«Öncelik (P0-P3)»: ekibin sektör yöntemine göre ne kadar acil olduğu: P0 hemen, P1 yakında, P2 planlanmalı, P3 sırası gelince. Kartların sırasını değiştirmez; hesap «Yöntem» sayfasında.",
                     "«Bağlantı yerleri»: hata veren, yönlenen ya da yanlış yazılmış her adres ve onu gösteren her sayfa bir satır: sayfa, bağlantı metni, href, konum, site haritası, önerilen hedef. Bağlantı veren sayfa yoksa «yalnızca site haritasında» yazar.",
                     "Bağlantılar Mac'in hızlı önizlemesinde çalışmaz; dosyayı Numbers, Excel veya Google Sheets ile açın."],
           "summary_cols": ["Kart", "Başlık", "Önem", "Sorun türü", "Öncelik (P0-P3)", "Sorumlu", "Efor", "Etkilenen adres", "Satırlara git"],
           "go": "Satırlara git →", "where": "Bağlantı yerleri",
           # DECISIONS 337: where each address with a problem is pointed at
           "where_cols": ["Kart", "Bozuk adres", "HTTP durumu", "Bağlantının bulunduğu sayfa", "Bağlantı metni", "Yazılan değer (href)",
                          "Konum", "Site haritasında mı?", "Site haritası dosyası", "Site haritasındaki <loc> metni", "<loc> satırı",
                          "Site haritası okuma zamanı", "Önerilen hedef", "Olası neden", "Bulgu kimliği", "Kural"],
           # DECISIONS 340: a link to an address that redirects to a working page is not a broken address
           "redirect": "Yönlendiren bağlantılar",
           "redirect_cols": ["Kart", "Bağlantının bulunduğu sayfa", "Bağlantı metni", "Konum", "Bağlantı verilen (eski) adres",
                             "Yönlendirme", "Doğrudan verilmesi gereken son adres", "Not", "Bulgu kimliği", "Kural"],
           "redirect_words": {"self": "yönlendirme bu sayfanın kendisinde bitiyor: bağlantının gerçekte nereye gitmesi gerektiğini kontrol edin",
                              "loc_old": "kaydedilmedi (eski denetim): adres, Maya'nın kaydettiği biçimde",
                              "read_approx": "yaklaşık: site haritası okuma adımının başı", "local": "TSİ"},
           "where_words": {"sitemap_only": "yalnızca site haritasında", "not_linked": "bağlantı bulunamadı", "yes": "Evet", "no": "Hayır",
                           "redirects": "yönlendiriyor", "not_recorded": "kaydedilmedi (eski denetim)",
                           "positions": {"menu": "menü", "footer": "altbilgi", "body": "gövde", "head": "<head>"},
                           "kinds": {"canonical": "kanonik etiketi", "hreflang": "hreflang etiketi"},
                           "suggest": {"remove": "kaldırın", "fix_nav": "bağlantıyı çalışan sayfaya verin (menü bağlantısı kalmalı)", "remove_or_redirect": "kaldırın veya yönlendirin",
                                       "fix_generator": "site haritası oluşturucuyu düzeltin", "fix_loop": "döngüyü düzeltin"},
                           "cause": "çıkarım: {page} sayfasındaki «{heading}» başlığından üretilmiş görünüyor",
                           "mistyped": "yanlış yazılmış adres"},
           "page_cols": ["Sayfa", "Okundu mu?", "Sayfa türü", "Önem puanı (0-100)", "Sorun sayısı", "En yüksek önem", "Sorunlar", "Kartlar"],
           "finding_cols": ["Sorun", "Önem", "Sorun türü", "Sayfa", "Okundu mu?", "Ölçülen değer", "Ne yapılmalı", "Kart", "Durum",
                            "Sayfa türü", "Sayfa önemi (0-100)", "Bulgu kimliği", "Kural", "Kontrol"],
           "empty": {"summary": "Bu denetimde PDF raporunda kart yok.",
                     "by_page": "Sayfa düzeyinde sorun yok: bulgular sitenin bütününü ya da alan adlarını ilgilendiriyor (bkz. «Bulgu bazında»).",
                     "by_finding": "Bu denetimde sitenin sorunu olarak listelenecek bulgu yok."}},
    "en": {"how": "How to read", "summary": "Summary", "by_page": "By page", "by_finding": "By finding",
           "lines": ["This file shows the problems the audit found, page by page; no technical knowledge is needed to read it.",
                     "\"Summary\": the cards of the PDF report, in the same order and with the same numbers. A card's \"Go to rows\" link opens that card's pages in \"By finding\".",
                     "\"By page\": one row per page with a problem, the most important page first. Importance is 0-100; when it is empty the page was not crawled, so it was not computed.",
                     "\"By finding\": one row per problem and page: the value measured on that page and what to do. Technical IDs are in the right-most columns.",
                     "To filter, use the arrow buttons in the header row (e.g. Card = 3 or Severity = High). Clicking an address opens the page in your browser.",
                     "Severity order: Blocker, High, Medium, Low, Info. \"Info\" rows are notes, not problems. \"Findings\" and the sheets after it are the team's technical detail.",
                     "\"Read?\": \"Yes\" is a page whose content was read and measured, \"No, not read\" an address known but not read; pages read come first, addresses not read follow as their own group.",
                     "\"Priority (P0-P3)\": how urgent a card is by the team's sector method: P0 now, P1 soon, P2 to plan, P3 when convenient. It does not change the card order; the formula is on the \"Method\" sheet.",
                     "\"Link locations\": one row per failing, redirecting or mistyped address and each page pointing to it: page, link text, href, place, sitemap, what to point to. With no linking page it says \"sitemap only\".",
                     "Links do not work in the Mac's Quick Look preview; open the file in Numbers, Excel or Google Sheets."],
           "summary_cols": ["Card", "Title", "Severity", "Issue type", "Priority (P0-P3)", "Owner", "Effort", "Affected addresses", "Go to rows"],
           "go": "Go to rows →", "where": "Link locations",
           "where_cols": ["Card", "Broken address", "HTTP status", "Page with the link", "Link text", "Written value (href)",
                          "Place", "In the sitemap?", "Sitemap file", "<loc> text in the sitemap", "<loc> line",
                          "Sitemap read at", "Point to instead", "Likely cause", "Finding ID", "Rule"],
           "redirect": "Redirecting links",
           "redirect_cols": ["Card", "Page with the link", "Link text", "Place", "Linked (old) address", "Redirect",
                             "Final address to link to directly", "Note", "Finding ID", "Rule"],
           "redirect_words": {"self": "the redirect ends on this page itself: check where the link should really go",
                              "loc_old": "not recorded (older audit): the address as Maya kept it",
                              "read_approx": "approximate: start of the sitemap step", "local": None},
           "where_words": {"sitemap_only": "sitemap only", "not_linked": "no link found", "yes": "Yes", "no": "No",
                           "redirects": "redirects", "not_recorded": "not recorded (older audit)",
                           "positions": {"menu": "menu", "footer": "footer", "body": "body", "head": "<head>"},
                           "kinds": {"canonical": "canonical tag", "hreflang": "hreflang tag"},
                           "suggest": {"remove": "remove", "fix_nav": "point the link at a working page (keep the menu link)", "remove_or_redirect": "remove or redirect",
                                       "fix_generator": "fix the sitemap generator", "fix_loop": "fix the loop"},
                           "cause": "inference: seems made from the heading “{heading}” on {page}",
                           "mistyped": "mistyped address"},
           "page_cols": ["Page", "Read?", "Page type", "Importance (0-100)", "Problems", "Highest severity", "Problems found", "Cards"],
           "finding_cols": ["Problem", "Severity", "Issue type", "Page", "Read?", "Measured value", "What to do", "Card", "Placement",
                            "Page type", "Page importance (0-100)", "Finding ID", "Rule", "Check"],
           "empty": {"summary": "The PDF report of this audit has no cards.",
                     "by_page": "No problem concerns single pages: the findings are about the whole site or its hosts (see \"By finding\").",
                     "by_finding": "This audit has no finding to list as a problem of the site."}},
}

WORDS = {
    "tr": {"findings": "Bulgular", "urls": "Etkilenen adresler", "key_pages": "Kilit sayfalar", "coverage": "Kapsam",
           "method_sheet": "Yöntem", "note": "Not",
           "key_pages_empty": {"reader_only": "Bu denetimde sayfa önemi hesaplanamadı: Maya'nın tarayıcısı engellendi, sayfalar başka bir okuma yoluyla okundu ve kayıtlı kopyalar sayfalar arası bağlantıları tutmuyor; önem bu bağlantılardan hesaplanır.",
                               "no_pages": "Bu denetimde içeriği okunan sayfa olmadığı için sayfa önemi hesaplanamadı."},
           "templates": "Şablonlar", "itype": {"issue": "Sorun", "warning": "Kontrol edin", "opportunity": "Fırsat"},
           "tpl_cols": ["Şablon", "Tür", "Okunan sayfa", "Sorunlu sayfa", "Sorun grubu", "Kartlar", "En yüksek önem", "Bulgu kimlikleri"],
           "tpl_kinds": {"home": "ana sayfa", "category": "kategori", "product": "ürün", "blog_article": "blog yazısı",
                         "location": "mağaza / konum", "policy": "politika", "utility": "yardımcı sayfa", "other": "diğer"},
           "cols": ["Bulgu kimliği", "Kontrol", "Kural", "Önem", "Sorun türü", "Güven (motor)", "Güven sınıfı", "Öncelik puanı", "Öncelik (P0-P3)",
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
                      "spoofed_googlebot": "Googlebot kimliğiyle yapılan isteğe 403/429",
                      "names_in_markup": "diğer marka adları yalnız yapısal veride"},
           "kind": {"page_cap": "Sayfa sınırı", "time_budget": "Süre sınırı", "reader": "Okuma yolu", "block_pages": "Engel sayfaları", "sampling": "Akıllı örneklem", "sources": "Kaynaklar", "edit_pages": "Düzenleme adresleri",
                    "not_assessed": "Değerlendirilmedi"},
           "page_type": {"home": "ana sayfa", "category": "kategori", "product": "ürün", "blog_article": "blog yazısı",
                         "location": "mağaza / konum sayfası", "policy": "politika sayfası", "utility": "yardımcı sayfa (arama, sepet, hesap)", "other": "diğer"},
           "home_languages": "ana sayfa ({n} dil)",
           "importance_unknown": "önem hesaplanamadı ({reason}, bkz. kart #{card})",
           "importance_reader": "önem hesaplanamadı: tarayıcımız engellendi, sayfa başka bir yolla okundu ve hangi sayfaların ona bağlantı verdiği bilinmiyor",
           # DECISIONS 321 (5): a sheet with no rows says why, in one line, never an empty sheet.
           "empty": {"findings": "Bu denetimde bulgu yok.",
                     "urls": "Hiçbir bulgu tek tek adres göstermiyor: bulgular sitenin bütününü ilgilendiriyor.",
                     "templates": {"reader_only": "Şablonlar çıkarılamadı: tarayıcımız engellendi, sayfalar başka bir yolla okundu ve sayfaların bağlantıları bilinmiyor; şablonlar okunan sayfaların adres düzeninden çıkarılır.",
                                   "no_pages": "Şablonlar çıkarılamadı: bu denetimde içeriği okunan sayfa yok.",
                                   "not_read": "Şablonlar çıkarılamadı: tarayıcımızın istediği sayfaların hiçbiri okunamadı (engel sayfası ya da hata); başka bir yolla okunan sayfalar şablonlara göre gruplanmıyor.",
                                   "no_template": "Okunan sayfalar arasında aynı adres düzenini (şablonu) paylaşan bir sayfa grubu bulunmadı; gruplanacak bir şey yok."},
                     "coverage": "Bu denetimde kayıtlı bir kapsam sınırı yok."},
           "importance_reasons": {"canonical": "kanonik sorunu", "redirect": "yönlendirme sorunu"},
           "method": [("Önem ağırlığı", "Engelleyici 100, Yüksek 40, Orta 15, Düşük 5, Bilgi 0"),
                      ("Güven ağırlığı", "ölçüldü 1,0 · tahmini 0,6 · çıkarım 0,5 · doğrulanmamış 0,4"),
                      ("Erişim", "1 + ln(1 + etkilenen ve okunan sayfaların önem puanı toplamı / 100), en çok 10; okunmayan adres katılmaz (ayrı sütunda sayılır); adressiz bulgu: ana sayfa"),
                      ("Sıra", "önce önem bandı, sonra bant içinde öncelik puanı"),
                      ("Kök neden grupları", "aynı nedeni ve tek düzeltmeyi paylaşan kurallar tek kart (sütun: Kök neden grubu)"),
                      ("Öncelik puanı", "önem x güven x erişim x iş önemi; efor gösterilir, puana girmez"),
                      ("Kartlar", "en çok 15: bütün Engelleyici/Yüksek gruplar, sonra bant ve puan sırasıyla"),
                      ("Öncelik (P0-P3)", "ekibin sektör yöntemi: 20 x etki (Engelleyici 5, Yüksek 4, Orta 3, Düşük 2) x sayfa ağırlığı x yaygınlık (1-5) x durum (1 ya da 0,5) / 3; P0 160 ve üstü, P1 80, P2 30, P3 0'dan büyük; ana sayfada ya da ilk iki sayfa türünün geniş bölümünde indeksleme engeli P0; elle P0 yapılabilir ya da kaldırılabilir; sırayı değiştirmez")]},
    "en": {"findings": "Findings", "urls": "Affected URLs", "key_pages": "Key pages", "coverage": "Coverage",
           "method_sheet": "Method", "note": "Note",
           "key_pages_empty": {"reader_only": "Page importance could not be worked out for this audit: Maya's crawler was blocked, the pages were read another way, and the saved copies keep no links between pages, which importance is computed from.",
                               "no_pages": "Page importance could not be worked out: no page's content was read in this audit."},
           "templates": "Templates", "itype": {"issue": "Issue", "warning": "Warning", "opportunity": "Opportunity"},
           "tpl_cols": ["Template", "Type", "Pages read", "Pages with problems", "Problem groups", "Cards", "Highest severity", "Finding IDs"],
           "tpl_kinds": {"home": "homepage", "category": "category", "product": "product", "blog_article": "blog article",
                         "location": "store / location", "policy": "policy", "utility": "utility page", "other": "other"},
           "cols": ["Finding ID", "Check", "Rule", "Severity", "Issue type", "Confidence (engine)", "Confidence class",
                    "Priority score", "Priority (P0-P3)", "Placement", "Card", "Group lead", "Confirm because", "Finding", "What to do",
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
                      "spoofed_googlebot": "403/429 to a request with Googlebot's user agent",
                      "names_in_markup": "the other brand names are only in structured data"},
           "kind": {"page_cap": "Page cap", "time_budget": "Time budget", "reader": "How pages were read", "block_pages": "Block pages", "sampling": "Smart sample", "sources": "Sources", "edit_pages": "Edit addresses",
                    "not_assessed": "Not assessed"},
           "page_type": {"home": "homepage", "category": "category", "product": "product", "blog_article": "blog article",
                         "location": "store / location page", "policy": "policy page", "utility": "utility page (search, cart, account)", "other": "other"},
           "home_languages": "homepage ({n} languages)",
           "importance_unknown": "importance not computed ({reason}, see card #{card})",
           "importance_reader": "importance not computed: our crawler was blocked, the page was read another way and which pages link to it is not known",
           # DECISIONS 321 (5): a sheet with no rows says why, in one line, never an empty sheet.
           "empty": {"findings": "This audit has no findings.",
                     "urls": "No finding names single addresses: the findings are about the site as a whole.",
                     "templates": {"reader_only": "Templates could not be worked out: our crawler was blocked, the pages were read another way and their links are not known; templates come from the address patterns of the pages read.",
                                   "no_pages": "Templates could not be worked out: no page's content was read in this audit.",
                                   "not_read": "Templates could not be worked out: none of the pages our crawler asked for could be read (a block page or an error), and pages read another way are not grouped by template.",
                                   "no_template": "Among the pages read, no group of pages shares one address pattern (a template); there is nothing to group."},
                     "coverage": "No coverage limit was recorded for this audit."},
           "importance_reasons": {"canonical": "canonical problem", "redirect": "redirect problem"},
           "method": [("Severity weight", "Blocker 100, High 40, Medium 15, Low 5, Info 0"),
                      ("Confidence weight", "measured 1.0 · estimated 0.6 · inferred 0.5 · unverified 0.4"),
                      ("Reach", "1 + ln(1 + summed importance of the affected pages that were read / 100), at most 10; addresses not read add nothing (counted in their own column); no address: the homepage"),
                      ("Order", "severity band first, then priority score within the band"),
                      ("Root-cause groups", "rules sharing one cause and one fix are one card (column: Root-cause group)"),
                      ("Priority score", "severity x confidence x reach x business; effort is shown, not scored"),
                      ("Cards", "at most 15: every Blocker/High group, then by band and score"),
                      ("Priority (P0-P3)", "the team's sector method: 20 x impact (Blocker 5, High 4, Medium 3, Low 2) x page weight x spread (1-5) x status (1 or 0.5) / 3; P0 at 160 or more, P1 80, P2 30, P3 above 0; an indexing blocker on the homepage or a large part of the first two page types is P0; P0 can be set or taken off by hand; it changes no order")]},
}


def _drop_empty_columns(header: list[str], rows: list[list]) -> tuple[list[str], list[list]]:
    keep = [i for i in range(len(header)) if any(i < len(r) and r[i] not in (None, "", []) for r in rows)]
    return [header[i] for i in keep], [[r[i] if i < len(r) else "" for i in keep] for r in rows]


def _manual(text: str, W: dict) -> str:
    """The manual check's result word in the appendix's language; who checked and what they saw stay as written."""
    word, sep, rest = text.partition(" · ")
    return f"{W['manual'].get(word, word)}{sep}{rest}" if text else ""


def block_pages_text(line: dict, lang: str) -> str:
    """DECISIONS 317: the block answers Maya's crawler got did not use up the page limit; what the page reader could
    read and read. One sentence for the PDF, the web summary and the appendix. DECISIONS 350: the reader's limit is on
    pages Maya did not read; the pages it read again are said apart from its new ones."""
    blocked, allowed, read = int(line.get("blocked") or 0), int(line.get("allowed") or 0), int(line.get("read") or 0)
    new = line.get("new")
    again = read - new if isinstance(new, int) else None
    time_first = line.get("stopped") == "time_limit" and (new if isinstance(new, int) else read) < allowed
    if lang == "tr":
        head = f"Engel sayfaları sayfa sınırına sayılmadı: Maya'nın tarayıcısı {blocked} istekte engel sayfası ya da 429 aldı; "
        if isinstance(new, int):
            body = (f"sayfa okuyucu Maya'nın okumadığı en çok {allowed} yeni sayfa okuyabilirdi, {new} yeni sayfa okudu"
                    + (f" (ayrıca Maya'nın okuduğu {again} sayfayı yeniden okudu)" if again else ""))
        else:
            body = f"sayfa okuyucu en çok {allowed} sayfa okuyabilirdi, {read} sayfa okudu"
        return head + body + (" (süre sınırı daha önce doldu)." if time_first else ".")
    req = "request" if blocked == 1 else "requests"
    head = f"Block pages did not count toward the page limit: Maya's crawler got a block page or a 429 on {blocked} {req}; "
    if isinstance(new, int):
        body = (f"the page reader could read up to {allowed} new {'page' if allowed == 1 else 'pages'} Maya had not read and "
                f"read {new}" + (f" (and read {again} of Maya's pages again)" if again else ""))
    else:
        body = f"the page reader could read up to {allowed} {'page' if allowed == 1 else 'pages'} and read {read}"
    return head + body + (" (the time limit came first)." if time_first else ".")


def edit_pages_text(line: dict, lang: str) -> str:
    """DECISIONS 351: CMS edit and preview addresses are their clean page, never a page of their own."""
    from urllib.parse import urlsplit
    ex = ", ".join((urlsplit(u).path or "/") + (f"?{urlsplit(u).query}" if urlsplit(u).query else "") for u in line.get("examples") or [])
    read, linked = int(line.get("read") or 0), int(line.get("linked") or 0)
    if lang == "tr":
        return (f"CMS düzenleme/önizleme adresleri ayrı sayfa sayılmadı: {read} okunan, {linked} bağlantı verilen adres"
                + (f" ({ex})" if ex else "") + "; okunan sayfa sayısına ve sayfa türlerine katılmadı, temiz adresleri sayıldı.")
    return (f"CMS edit and preview addresses were not counted as pages of their own: {read} read, {linked} linked"
            + (f" ({ex})" if ex else "") + "; left out of the pages read and the page types, their clean addresses counted.")


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
    if kind == "block_pages":
        return block_pages_text(line, lang)
    if kind == "edit_pages":  # DECISIONS 351
        return edit_pages_text(line, lang)
    if kind == "sources":  # DECISIONS 348
        from .read_sources import lines as source_lines
        return " ".join(source_lines(line, lang))
    if kind == "sampling":  # DECISIONS 327
        from .sampling import coverage_text as sampled_text
        return sampled_text(line.get("rows") or [], lang)
    if kind == "reader":
        shown = (title(line.get("check_id") or "ACC-9", line.get("title") or "") if title else None) or line.get("title")
        return f"{shown} ({', '.join(line.get('finding_ids') or [])})"
    if kind == "not_assessed" and (line.get("part") or line.get("reason")) and (label or sentence):
        part = (label(line.get("part")) if label and line.get("part") else None) or line.get("part") or ""
        reason = (sentence(line.get("reason")) if sentence and line.get("reason") else None) or line.get("reason") or ""
        return f"{part}: {reason}".strip(": ")
    return line.get("text") or W["kind"].get(kind, kind)


BUSINESS_WORDS = {
    "tr": {"type": "İş türü", "weights": "Sayfa türü ağırlığı", "relevance": "İş önemi",
           "chosen": {"user": "seçildi", "suggestion": "önerildi; değiştirilebilir"},
           "rest": {"other": "eşleşmeyen sayfa", "policy": "politika / yasal", "utility": "yardımcı sayfa"},
           "links": "Diğer: iş türü profili kullanılmadı; sayfa önemi genel sayfa türünden (ana sayfa 100, kategori 80, ürün 70, "
                    "blog yazısı 60, diğer 50, politika 15, yardımcı 0) ve bağlantılardan: %50 bağlantı puanı, %25 tıklama "
                    "derinliği, %25 genel sayfa türü",
           "relevance_text": "puanda 1,0 (çarpan değil); iş türü puana sayfa önemiyle girer: %50 sayfa türü ağırlığı + %35 "
                             "iç bağlantı puanı + %15 tıklama derinliği puanı. Bu önem «Erişim»i ve P0-P3'teki sayfa "
                             "ağırlığını (ağırlık / 100) belirler",
           "relevance_links": "puanda 1,0 (çarpan değil); sayfa önemi «Erişim»i ve P0-P3'teki sayfa ağırlığını belirler"},
    "en": {"type": "Business type", "weights": "Page type weight", "relevance": "Business relevance",
           "chosen": {"user": "chosen", "suggestion": "suggested; can be changed"},
           "rest": {"other": "unmatched page", "policy": "policy / legal", "utility": "utility page"},
           "links": "Other: no business-type profile; page importance from the general page type (homepage 100, "
                    "category 80, product 70, blog article 60, other 50, policy 15, utility 0) and links: 50% link score, "
                    "25% click depth, 25% general page type",
           "relevance_text": "1.0 in the score (not a multiplier); the business type enters through page importance: 50% "
                             "page type weight + 35% internal link score + 15% click-depth score. That importance sets "
                             "\"Reach\" and the page weight of P0-P3 (weight / 100)",
           "relevance_links": "1.0 in the score (not a multiplier); page importance sets \"Reach\" and the page weight of P0-P3"},
}


def method_rows(selection: dict, lang: str) -> list[list[str]]:
    """The "Yöntem" sheet: the fixed method, with the business type this audit's importance actually used and its
    page type weights in place of the old "1.0 until business-type profiles exist" (DECISIONS 339)."""
    W, B = WORDS[lang], BUSINESS_WORDS[lang]
    rows = [list(m) for m in W["method"]]
    at = next((i for i, m in enumerate(rows) if m[0] in ("Öncelik puanı", "Priority score")), len(rows))
    info = selection.get("business_type") or {}
    from . import business_types as bt
    pid = info.get("id")
    if pid and pid != bt.DEFAULT and pid in bt.profiles():
        prof = bt.profile(pid)
        how = B["chosen"].get(info.get("chosen_by") or "suggestion", B["chosen"]["suggestion"])
        types = [f"{(t.get('label') or {}).get(lang) or t['id']} {t['weight']}" for t in prof["page_types"]]
        if not any(t["id"] == "home" for t in prof["page_types"]):
            types.append(f"{bt.SPECIAL['home'][lang]} {bt.weight(prof, 'home')}")
        types += [f"{B['rest']['other']} {bt.UNMATCHED_WEIGHT}", f"{B['rest']['policy']} {bt.POLICY_WEIGHT}",
                  f"{B['rest']['utility']} {bt.UTILITY_WEIGHT}"]
        add = [[B["type"], f"{bt.label(pid, lang)} ({how})"], [B["weights"], " · ".join(types)],
               [B["relevance"], B["relevance_text"]]]
    else:
        add = [[B["type"], B["links"]], [B["relevance"], B["relevance_links"]]]
    return rows[:at] + add + rows[at:]


def sheets(selection: dict, lang: str = "tr", lists: dict | None = None,
           title: Callable[[str, str], str] | None = None, fix: Callable[[str], str] | None = None,
           label: Callable[[str], str] | None = None, line: Callable[[str], str] | None = None,
           todos: list[dict] | None = None, words: Callable[[dict], dict | None] | None = None,
           places: dict | None = None, maya: dict | None = None) -> list[dict]:
    """The appendix's sheets: the four for readers who are not technical (DECISIONS 322), then the technical ones.
    `todos`: the team report's cards, so "Özet" has the PDF's cards and the rows their numbers; `words(finding)`: the
    text library's plain problem name and fix. `maya`: {"summary", "report", "evidence"} of the Maya data attached to
    the audit (DECISIONS 352), whose sheets come after the reader sheets; without it Kapsam says none was attached."""
    from . import checklist
    # DECISIONS 342: the SEO team's 165-item checklist, after the reader sheets
    listed = checklist.sheets(selection, lang, todos, title) if selection.get("_checklist_facts") else []
    reader = reader_sheets(selection, lang, lists, title=title, fix=fix, todos=todos, words=words, places=places)
    technical = technical_sheets(selection, lang, lists, title, fix, label, line)
    if maya is None or lang != "tr":
        return reader + listed + technical
    from . import maya_sheets
    made = maya_sheets.build(maya.get("summary"), maya.get("report") or {}, maya.get("evidence"),
                             selection.get("_importance"), (selection.get("business_type") or {}).get("id"))  # DECISIONS 357
    R, W = READ[lang], WORDS[lang]
    for sheet in reader:
        if sheet["name"] == R["how"]:
            sheet["rows"] = list(sheet["rows"]) + [[x] for x in made["howto"]]
            break
    for sheet in technical:
        if sheet["name"] == W["coverage"]:
            sheet["rows"] = list(sheet["rows"]) + [["Maya verisi", text, ""] for text in made["coverage"]]
        elif sheet["name"] == W["method_sheet"]:
            sheet["rows"] = list(sheet["rows"]) + [list(m) for m in made["method"]]
    return reader + made["sheets"] + listed + technical


def _link(url: str | None, text: str) -> dict | str:
    return {"text": text, "link": url} if url and url.startswith(("http://", "https://")) else text


def redirects_to_working(r: dict) -> bool:
    """A link (or canonical, hreflang) to an address that redirects and ends on a working page (DECISIONS 340)."""
    final = r.get("final_status")
    return (r.get("kind") != "sitemap" and bool(r.get("ends_at")) and r.get("ends_at") != r.get("links_to")
            and not r.get("loop") and isinstance(final, int) and 200 <= final < 400)


def read_time(value: str | None, approx: bool, lang: str) -> str:
    """"2026-11-11 12:07:49 UTC (15:07:49 TSİ)" (Turkish time is UTC+3 all year); the approximation said."""
    from datetime import datetime, timedelta
    if not value:
        return ""
    R = READ[lang]["redirect_words"]
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    text = at.strftime("%Y-%m-%d %H:%M:%S UTC")
    if R["local"]:
        text += f" ({(at + timedelta(hours=3)).strftime('%H:%M:%S')} {R['local']})"
    return text + (f" — {R['read_approx']}" if approx else "")


def where_rows(places: dict | None, todos: list[dict] | None, lang: str) -> list[list]:
    """DECISIONS 337: the "Bağlantı yerleri" rows: one per address with a problem and the page or entry that names it
    (`final.broken_link_cards`), numbered by the PDF's cards. DECISIONS 340: a sitemap entry's <loc> as the file
    writes it, its line and when the file was read; links to addresses that redirect to a working page are in
    `redirect_rows`, not here."""
    from urllib.parse import unquote
    R = READ[lang]
    Wd, Rw = R["where_words"], R["redirect_words"]
    shown = lambda u: _link(u, unquote(u or ""))  # noqa: E731  readable letters, the real address behind the link
    card = {fid: t["n"] for t in todos or [] for fid in t.get("finding_ids") or []}
    out = []
    for fid, rows in (places or {}).items():
        for r in rows:
            if redirects_to_working(r):
                continue
            kind = r.get("kind")
            first, final_status = r.get("status"), r.get("final_status")
            if r.get("ends_at") and r.get("ends_at") != r.get("links_to"):
                status = f"{first or Wd['redirects']} → {final_status}" if final_status else str(first or Wd["redirects"])
            else:
                status = str(first or final_status or "")
            if kind == "sitemap":
                page = Wd["sitemap_only"]
            elif kind == "not_linked":
                page = Wd["not_linked"]
            else:
                page = shown(r.get("source"))
            text = Wd["kinds"].get(kind, "") + (f" ({r['link_text']})" if kind == "hreflang" and r.get("link_text") else "") \
                if kind in ("canonical", "hreflang") else (r.get("link_text") or "")
            href = r.get("href") or (Wd["not_recorded"] if kind == "link" else "")
            url = r.get("replacement_url")
            suggest = shown(url) if url else Wd["suggest"].get(r.get("suggested") or "remove", r.get("suggested") or "")
            if "target_basis" in r:  # DECISIONS 346: the 301 target the card gives this sitemap address, worded alike
                from .checks.team_rules import target_words
                # an address made from a heading also needs the generator fixed (DECISIONS 337)
                suggest = target_words(r, lang) + (f"; {Wd['suggest']['fix_generator']}" if r.get("suggested") == "fix_generator" else "")
            heading = r.get("heading") or {}
            cause = (Wd["cause"].format(page=unquote(heading.get("page") or ""), heading=heading.get("heading") or "") if heading else
                     Wd["mistyped"] if r.get("mistyped") else "")
            if kind == "sitemap":  # the text to search for in the file: never decoded
                loc = r.get("sitemap_loc") or r.get("links_to") or ""
                line = r.get("sitemap_line") if r.get("sitemap_loc") else Rw["loc_old"]
                read = read_time(r.get("sitemap_read_at"), bool(r.get("sitemap_read_approx")), lang)
            else:
                loc, line, read = "", "", ""
            out.append([card.get(fid, ""), shown(r.get("links_to")), status, page, text, href,
                        Wd["positions"].get(r.get("position") or "", ""), Wd["yes"] if r.get("in_sitemap") or kind == "sitemap" else Wd["no"],
                        unquote(r.get("sitemap_file") or ""), loc, line if line is not None else "", read,
                        suggest, cause, fid, r.get("rule_id") or ""])
    return sorted(out, key=lambda row: (row[0] == "", row[0] if row[0] != "" else 0))


def redirect_rows(places: dict | None, todos: list[dict] | None, lang: str) -> list[list]:
    """DECISIONS 340: "Yönlendiren bağlantılar": one row per link to an address that redirects to a working page:
    the page with the link, the (old) address it links to, the redirect, and the final address to link to directly.
    When the redirect ends on the linking page itself, the note says so (a link to itself is no fix)."""
    from urllib.parse import unquote
    R = READ[lang]
    Wd, Rw = R["where_words"], R["redirect_words"]
    shown = lambda u: _link(u, unquote(u or ""))  # noqa: E731
    card = {fid: t["n"] for t in todos or [] for fid in t.get("finding_ids") or []}
    out = []
    for fid, rows in (places or {}).items():
        for r in rows:
            if not redirects_to_working(r):
                continue
            kind = r.get("kind")
            text = (Wd["kinds"].get(kind, "") + (f" ({r['link_text']})" if kind == "hreflang" and r.get("link_text") else "")
                    if kind in ("canonical", "hreflang") else (r.get("link_text") or ""))
            hop = f"{r.get('status') or Wd['redirects']} → {r.get('final_status')}"
            same = bool(r.get("source")) and r.get("source") == r.get("ends_at")
            out.append([card.get(fid, ""), shown(r.get("source")) if r.get("source") else Wd["not_linked"], text,
                        Wd["positions"].get(r.get("position") or "", ""), shown(r.get("links_to")), hop,
                        shown(r.get("ends_at")), Rw["self"] if same else "", fid, r.get("rule_id") or ""])
    return sorted(out, key=lambda row: (row[0] == "", row[0] if row[0] != "" else 0))


def reader_sheets(selection: dict, lang: str = "tr", lists: dict | None = None, *, title=None, fix=None,
                  todos: list[dict] | None = None, words=None, places: dict | None = None) -> list[dict]:
    """DECISIONS 322: "Nasıl okunur", "Özet" (the PDF's cards, each linked to its first row), "Sayfa bazında" (one row
    per page with a problem) and "Bulgu bazında" (one row per finding and page, with the value measured there)."""
    from . import page_rows
    W, R = WORDS[lang], READ[lang]
    rows = page_rows.finding_rows(selection, lists, lang, todos=todos, words=words, title=title, fix=fix)
    _, cards = page_rows.card_of(selection, todos, lang, title)
    sev = lambda s: W["severity"].get(s, s or "")  # noqa: E731
    profile_id = (selection.get("business_type") or {}).get("id")  # DECISIONS 350: the profile's own type words
    ptype = lambda t: page_rows.type_word(t, lang, profile_id, W["page_type"])  # noqa: E731
    found = [[r["title"], sev(r["severity"]), W["itype"].get(r["issue_type"], ""),
              _link(r["url"], r["address"]), page_rows.read_word(r["read"], lang), r["value"], r["fix"], r["card"] if r["card"] is not None else "",
              W["placement"].get(r["placement"], r["placement"] or ""), ptype(r["page_type"]),
              r["importance"] if isinstance(r["importance"], (int, float)) else "",
              r["finding_id"], r["rule_id"] or "", r["check_id"] or ""] for r in rows]
    first_row: dict[int, int] = {}
    for i, r in enumerate(rows, 2):
        if r["card"] is not None:
            first_row.setdefault(r["card"], i)
    addresses: dict[int, set] = {}
    for r in rows:
        if r["card"] is not None:
            addresses.setdefault(r["card"], set()).add(r["url"] or r["address"])
    where = "'" + R["by_finding"].replace("'", "''") + "'"
    summary = [[c["n"], c.get("title") or "", sev(c.get("severity")),
                W["itype"].get(c.get("issue_type") or "", "") if c.get("severity") in ("S1", "S2", "S3", "S4") else "",
                c.get("p_level") or "",  # DECISIONS 324
                c.get("owner") or "", c.get("effort") or "", len(addresses[c["n"]]) if c["n"] in addresses else c.get("addresses") or 0,
                {"text": R["go"], "location": f"{where}!A{first_row[c['n']]}"} if c["n"] in first_row else ""]
               for c in cards]
    by_page = [[_link(p["url"], p["url"]), page_rows.read_word(p["read"], lang), ptype(p["page_type"]),
                p["importance"] if isinstance(p["importance"], (int, float)) else "", p["problems"], sev(p["worst"]),
                "; ".join(p["names"]), ", ".join(str(n) for n in p["cards"])] for p in page_rows.page_table(rows)]
    out = [{"name": R["how"], "header": [R["how"]], "rows": [[x] for x in R["lines"]], "widths": [140],
            "frozen": False, "filter": False}]
    for key, header, body, widths in (("summary", R["summary_cols"], summary, [7, 60, 12, 14, 12, 22, 10, 12, 18]),
                                      ("by_page", R["page_cols"], by_page, [70, 16, 22, 12, 10, 14, 80, 10]),
                                      ("by_finding", R["finding_cols"], found, [42, 12, 13, 60, 16, 48, 60, 7, 16, 20, 12, 18, 24, 10])):
        if body:
            out.append({"name": R[key], "header": header, "rows": body, "widths": widths})
        else:  # one line saying why, never an empty sheet (DECISIONS 321 (5))
            out.append({"name": R[key], "header": [W["note"]], "rows": [[R["empty"][key]]], "widths": [140]})
    where = where_rows(places, todos, lang)
    if where:  # DECISIONS 337: only when the audit has an address pointed at from somewhere
        out.append({"name": R["where"], "header": R["where_cols"], "rows": where,
                    "widths": [7, 60, 14, 60, 30, 40, 11, 14, 40, 60, 12, 34, 50, 50, 18, 24]})
    moved = redirect_rows(places, todos, lang)  # DECISIONS 340
    if moved:
        out.append({"name": R["redirect"], "header": R["redirect_cols"], "rows": moved,
                    "widths": [7, 60, 30, 11, 60, 14, 60, 50, 18, 24]})
    return out


def technical_sheets(selection: dict, lang: str = "tr", lists: dict | None = None,
                     title: Callable[[str, str], str] | None = None, fix: Callable[[str], str] | None = None,
                     label: Callable[[str], str] | None = None, line: Callable[[str], str] | None = None) -> list[dict]:
    from .client_selection import host_level
    from .page_rows import display_address
    W = WORDS[lang]
    rows, urls = [], []
    for r in appendix_rows(selection, lists):
        t = (title(r["check_id"], r["title"]) if title else None) or r["title"]
        x = (fix(r["how_to_fix"]) if fix and r["how_to_fix"] else None) or r["how_to_fix"]
        placement = W["placement"].get(r["placement"], r["placement"])
        rows.append([r["finding_id"], r["check_id"], r["rule_id"], W["severity"].get(r["severity"], r["severity"]),
                     W["itype"].get(r.get("issue_type") or "issue", ""), r["confidence"], W["class"].get(r["confidence_class"], r["confidence_class"]), r["priority"], r.get("p_level") or "",
                     placement, r["card"], r["group_lead"] if r["group_lead"] != r["finding_id"] else "",
                     W["reason"].get(r["confirm_reason"], r["confirm_reason"]) if r["confirm_reason"] else "",
                     t, x, r["scope_count"], len(r["urls"]), r.get("pages_read"), r.get("not_read"),
                     r.get("merge_group") or "", _manual(r.get("manual") or "", W)])
        hosts = host_level(r["finding"]) if r.get("finding") else None
        for u in r["urls"]:  # DECISIONS 322 (7): a host-level finding's host roots as plain host names
            urls.append([r["finding_id"], placement, W["severity"].get(r["severity"], r["severity"]), display_address(u, hosts)])
    # DECISIONS 312: the homepage's language versions are one row; the cell lists every address.
    pages = [[p["rank"], "\n".join(p.get("languages") or [p["url"]]),
              W["home_languages"].format(n=len(p["languages"])) if p.get("languages") else W["page_type"].get(p["page_type"], p["page_type"]),
              (W["importance_reader"] if (p.get("importance_unknown") or {}).get("reason") == "reader_only" else
               W["importance_unknown"].format(reason=W["importance_reasons"][p["importance_unknown"]["reason"]],
                                              card=p["importance_unknown"]["card"])) if p.get("importance_unknown") else p["importance"],
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
    for name, header, body, widths in ((W["findings"], W["cols"], rows, [16, 8, 22, 11, 13, 11, 16, 9, 10, 16, 6, 16, 26, 70, 70, 9, 9, 10, 10, 20, 60]),
                                       (W["urls"], W["url_cols"], urls, [16, 16, 11, 90]),
                                       (W["key_pages"], W["page_cols"], pages, [6, 70, 12, 10, 14, 12, 10]),
                                       (W["templates"], W["tpl_cols"], tpls, [40, 16, 12, 12, 12, 16, 14, 60]),
                                       (W["coverage"], W["cov_cols"], cov, [18, 110, 40]),
                                       (W["method_sheet"], W["method_cols"], method_rows(selection, lang), [22, 100])):
        if name == W["key_pages"] and not selection["key_pages"]:
            out.append({"name": name, "header": [W["note"]], "rows": body, "widths": [140]})
            continue
        if not body:  # DECISIONS 321 (5): one line saying why the sheet has no rows
            out.append({"name": name, "header": [W["note"]], "rows": [[_empty_reason(name, selection, W)]], "widths": [140]})
            continue
        h, b = _drop_empty_columns(header, body) if body else (header, body)
        keep = [header.index(c) for c in h]
        out.append({"name": name, "header": h, "rows": b, "widths": [widths[i] for i in keep]})
    return out


def _empty_reason(name: str, selection: dict, W: dict) -> str:
    """Why a sheet has no rows (DECISIONS 321 (5)). Templates: no page could be scored (the key pages' reason: the
    crawler was blocked and the pages were read another way, or nothing was read), else no shared address pattern."""
    empty = W["empty"]
    if name == W["templates"]:
        reason = selection.get("templates_reason")
        return empty["templates"].get(reason) or empty["templates"]["no_template"]
    key = {W["findings"]: "findings", W["urls"]: "urls", W["coverage"]: "coverage"}.get(name)
    return empty.get(key) or empty["findings"]


def build(selection: dict, lang: str = "tr", lists: dict | None = None, text_check=None, **wording) -> bytes:
    """`text_check`: the release gate's text check (DECISIONS 353), a record or a function returning one once every
    sheet is written (so the sentences the sheets showed untranslated are in it); its sheet "Kontrol raporu" comes last."""
    made = sheets(selection, lang, lists, **wording)
    if text_check is not None:
        from . import text_gate
        made.append(text_gate.sheet(text_check() if callable(text_check) else text_check, lang))
    return xlsx.workbook(made)


def finding_ids(data: bytes, lang: str = "tr") -> set[str]:
    """The finding ids an appendix file lists (the technical findings sheet's first column), for RG-17 on the written
    file. The reader sheets come first since DECISIONS 322, so the sheet is found by its name in either language."""
    book = xlsx.read(data)
    names = [WORDS[lang]["findings"]] + [w["findings"] for w in WORDS.values()]
    first = next((book[n] for n in names if n in book), None)
    if first is None:
        first = next(iter(book.values()), [])
    if first and first[0] and first[0][0] in {w["note"] for w in WORDS.values()}:
        return set()  # an empty findings sheet holds one line saying why (DECISIONS 321 (5)), not an id
    return {row[0] for row in first[1:] if row and row[0]}


assert set(SEVERITY_WEIGHT) == set(WORDS["tr"]["severity"]) and set(CONFIDENCE_WEIGHT) == set(WORDS["tr"]["class"])
