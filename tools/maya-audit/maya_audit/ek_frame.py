"""DECISIONS 376: the Ek as the team's full client file. Its frame: the sheets in the team's order, the Maya band on
every sheet (the brand, the sheet, "← Kapak" and the sheet's source with its own period), and the "Kapak" sheet
(scope, source files, the measurement periods table, the colour legend and a linked sheet guide).

Every source keeps its own period: periods are listed side by side, never summed or merged. A number Maya computes
itself where the team used Maya's dashboard says "Maya dışa aktarımından hesaplandı". Global for every audit; the
brands the plan was made from are only test cases (docs/proposals/EK-FULL-FILE.md).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from urllib.parse import urlsplit

# The sheets, in the team's order (Efsa's final file), then Maya's own sheets she left out (owner's D1: listed last).
# key: (Turkish name, English name)
SHEETS: dict[str, tuple[str, str]] = {
    "cover": ("Kapak", "Cover"),
    "exec": ("Yönetici özeti", "Executive summary"),
    "actions": ("Aksiyon planı", "Action plan"),
    "expert": ("Uzman teyidi", "Expert check"),
    "groups": ("Sayfa grupları", "Page groups"),
    "locations": ("Konum dizini", "Location index"),
    "how": ("Nasıl okunur", "How to read"),
    "sc_summary": ("Search Console özeti", "Search Console summary"),
    "summary": ("Özet", "Summary"),
    "key_pages": ("Kilit sayfalar", "Key pages"),
    "traffic": ("Trafiğe göre öncelik", "Priority by traffic"),
    "by_page": ("Sayfa bazında", "By page"),
    "by_finding": ("Bulgu bazında", "By finding"),
    "findings": ("Bulgular", "Findings"),
    "urls": ("Etkilenen adresler", "Affected URLs"),
    "templates": ("Şablonlar", "Templates"),
    "where": ("Bağlantı yerleri", "Link locations"),
    "redirect": ("Yönlendiren bağlantılar", "Redirecting links"),
    "changed": ("Önceki denetimden değişenler", "Changed since the previous audit"),
    "checklist_summary": ("Kontrol listesi özeti", "Checklist totals"),
    "checklist": ("Kontrol listesi", "Checklist"),
    "sc_pages": ("SC sayfaları", "SC pages"),
    "sc_queries": ("SC sorgular", "SC queries"),
    "sc_opportunities": ("SC fırsatlar", "SC opportunities"),
    "ai_pages": ("AI alıntılanan sayfalar", "Pages cited by AI"),
    "competitor_topics": ("Rakip - Konu", "Competitors - Topics"),
    "competitor_pages": ("Rakip - Sayfa yapısı", "Competitors - Page structure"),
    "coverage": ("Kapsam", "Coverage"),
    "method": ("Yöntem", "Method"),
    "competitor_notes": ("Rakip yöntem notları", "Competitor method notes"),
    "source_map": ("Kaynak eşlemesi", "Source map"),
    "overview": ("Genel durum", "Overview"),
    "organic_summary": ("Organik×AI - Özet", "Organic×AI - Summary"),
    "organic_segments": ("Organik×AI - Segmentler", "Organic×AI - Segments"),
    "detail": ("Sayfa detay", "Page detail"),
}
ORDER = list(SHEETS)
INTERNAL = ("Kontrol raporu", "Text check", "Düzeltme kaydı", "Fix log")  # D1: the team file, never the client Ek

GROUPS = {"tr": {"maya": "Maya özeti", "audit": "Teknik denetim", "data": "Search Console / AI (Maya dışa aktarımı)",
                 "rivals": "Rakip analizi", "method": "Yöntem ve izlenebilirlik"},
          "en": {"maya": "Maya summary", "audit": "Technical audit", "data": "Search Console / AI (Maya export)",
                 "rivals": "Competitor analysis", "method": "Method and traceability"}}
# key: (group, Turkish description, English description)
ABOUT = {
    "cover": ("maya", "Kapsam, kaynaklar, ölçüm dönemleri ve bu rehber", "Scope, sources, measurement periods and this guide"),
    "exec": ("maya", "Ana bulgular, kanıtları ve karar bekleyen konular", "Main findings, their evidence and open decisions"),
    "actions": ("maya", "Aksiyonlar: öncelik, kanıt bağlantısı, uzman ve uygulama alanları",
                "Actions: priority, evidence link, expert and delivery fields"),
    "expert": ("maya", "Uzman kararı bekleyen maddeler", "Items waiting for an expert decision"),
    "groups": ("maya", "Sayfa grubu › adres › aksiyon", "Page group › address › action"),
    "locations": ("maya", "Her aksiyonun satırı, kanıtı ve PDF sayfası", "Each action's row, evidence and PDF page"),
    "how": ("method", "Sekmelerin okuma kılavuzu", "How to read the sheets"),
    "sc_summary": ("data", "Site geneli tık, gösterim, cihaz, niyet, dönemler ve dikkat notları",
                   "Site-wide clicks, impressions, device, intent, periods and notes"),
    "summary": ("audit", "PDF raporundaki kartlar; «Satırlara git» kartın satırlarını açar",
                "The PDF report's cards; \"Go to rows\" opens a card's rows"),
    "key_pages": ("audit", "Önem puanına göre kilit sayfalar", "Key pages by importance"),
    "traffic": ("data", "Sorunlu sayfalar, Search Console tıkına göre", "Pages with problems, by Search Console clicks"),
    "by_page": ("audit", "Sorunlu her sayfa bir satır", "One row per page with a problem"),
    "by_finding": ("audit", "Her bulgu × sayfa bir satır: ölçülen değer ve ne yapılacağı",
                   "One row per finding and page: the measured value and what to do"),
    "findings": ("audit", "Her bulgu kimliği: önem, güven, P0–P3, ne yapılmalı",
                 "Every finding ID: severity, confidence, P0–P3, what to do"),
    "urls": ("audit", "Bulgu kimliği × adres", "Finding ID × address"),
    "templates": ("audit", "Şablon bazında sorun özeti", "Problems per template"),
    "where": ("audit", "Hata veren adresler ve onlara bağlantı veren yerler", "Failing addresses and where they are linked from"),
    "redirect": ("audit", "Yönlendirmeye giden iç bağlantılar", "Internal links to redirects"),
    "changed": ("audit", "Önceki denetime göre değişenler", "What changed since the previous audit"),
    "checklist_summary": ("audit", "Kontrol listesinin grup sonuçları", "The checklist's results per group"),
    "checklist": ("audit", "SEO kontrol listesinin maddeleri ve sonuçları", "The SEO checklist's items and results"),
    "sc_pages": ("data", "Search Console'da tık alan sayfalar ve denetim durumu", "Pages with Search Console clicks and their audit status"),
    "sc_queries": ("data", "Search Console sorguları", "Search Console queries"),
    "sc_opportunities": ("data", "Yamyamlaşma, yüksek gösterim/düşük CTR, yakın sıra",
                         "Cannibalization, high impressions/low CTR, striking distance"),
    "ai_pages": ("data", "AI cevaplarında alıntılanan sayfalar", "Pages cited in AI answers"),
    "competitor_topics": ("rivals", "Konular: marka ve lider rakip, citation payı, öneri",
                          "Topics: the brand and the leading rival, citation share, advice"),
    "competitor_pages": ("rivals", "Marka / rakip / karşılaştırma sitesi sayfa yapısı", "Page structure: brand, rival, comparison site"),
    "coverage": ("method", "Değerlendirilmeyenler ve örneklem", "What was not assessed, and the sample"),
    "method": ("method", "Öncelik puanı ve P0–P3 hesabı", "Priority score and P0–P3"),
    "competitor_notes": ("rivals", "Rakip sekmelerini doğru okumak için yöntem satırları", "Method lines for the competitor sheets"),
    "source_map": ("method", "Her sekmenin kaynağı ve dönemi", "Each sheet's source and period"),
    "overview": ("data", "Search Console ve AI genel durumu", "Search Console and AI overview"),
    "organic_summary": ("data", "Organik × AI segmentlerinin özeti", "Organic × AI segments, summary"),
    "organic_segments": ("data", "Organik × AI segmentleri, sayfa sayfa", "Organic × AI segments, page by page"),
    "detail": ("data", "Seçilen sayfaların ayrıntısı", "Detail of the selected pages"),
}
# Maya's own sheets and the Maya data groups they need (maya_data.NEEDS)
DATA_OF = {"overview": "overview", "organic_summary": "organic_ai", "organic_segments": "organic_ai",
           "detail": "page_detail", "competitor_topics": "competitors", "competitor_pages": "competitors"}

MONTHS = {"tr": ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"],
          "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                 "November", "December"]}

W = {
    "tr": {"band": "maya  ·  {brand} SEO analizi  ·  {sheet}", "brand_none": "site",
           "back": "← Kapak", "source": "Kaynak: {what}", "audit": "Maya Audit teknik denetimi · tarama {date}",
           "audit_no_date": "Maya Audit teknik denetimi · tarama tarihi kaydedilmedi",
           "maya": "Maya dışa aktarımı ({sets})", "computed": "Maya dışa aktarımından hesaplandı",
           "method": "Maya Audit (yöntem)", "plus": " + ",
           "title": "SEO ve AI görünürlük analizi — {host}",
           "title_parts": {"audit": "teknik denetim", "data": "Search Console ve AI alıntıları", "rivals": "rakip karşılaştırması"},
           "review_done": "SEO uzmanı değerlendirmesinden geçmiştir ({date})",
           "review_wait": "Uzman teyidi bekliyor: «Uzman teyidi» sekmesindeki {open} maddenin kararı verilmedi",
           "review_none": "Uzman teyidi gereken madde yok",
           "made": "Hazırlama tarihi: {date}. Bu tarih metriklerin ölçüm tarihi değildir; her verinin kendi dönemi aşağıdaki tabloda.",
           "scope": "Kapsam", "covered": "Ne kapsanıyor?", "not_covered": "Ne kapsanmıyor?",
           "covered_audit": "Maya Audit teknik denetimi: {host}, tarama {date}; {read} sayfa okundu, bilinen ama okunmayan adres {unread}.",
           "covered_data": " Maya dışa aktarımı: {n} veri seti ({sets}); her biri kendi döneminde.",
           "not_assessed": "Denetimde değerlendirilmeyen {n} konu «Kapsam» sekmesinde.",
           "no_data": "Maya verisi eklenmedi: Search Console ve AI alıntı sekmeleri bu dosyada yok.",
           "no_ga4": "GA4 verisi yok (ziyaret, oturum, dönüşüm ölçülmedi).",
           "no_inspection": "Search Console URL denetimi ve dizin kapsamı raporu yok (Maya dışa aktarımında bulunmuyor).",
           "no_estimate": "Trafik ya da dönüşüm etkisi tahmini yapılmaz.",
           "files": "Kaynak dosyalar", "file_cols": ["Dosya", "Kapsama alınan", "Not"],
           "file_audit": "Maya Audit teknik denetimi ({id})", "file_audit_used": "{n} sekme",
           "file_audit_note": "Tarama {date}; motor sürümü «Yöntem» sekmesinin son satırında",
           "file_rows": "{n} satır", "file_note": "Maya dışa aktarımı · {dataset}",
           "periods": "Ölçüm dönemleri (toplanmaz, birleştirilmez)", "period_cols": ["Veri", "Dönem", "Sekme"],
           "period_audit": "Teknik tarama", "period_none": "dosyada dönem yok (anlık görüntü)",
           "legend": "Renk göstergesi",
           "legend_rows": [("Kaynak veri", "Denetimin ya da Maya dışa aktarımının ölçtüğü değerler (beyaz)", None),
                           ("Hesaplanan / Maya metni", "Maya'nın kaynaktan hesapladığı ya da yazdığı alanlar", "computed"),
                           ("Uzman / marka girişi", "SEO uzmanının ya da marka ekibinin dolduracağı alanlar (boş gelir)", "input"),
                           ("Yeşil başlık", "Search Console ve AI alıntı sütunları (Maya dışa aktarımı)", "green"),
                           ("Öncelik etiketi", "P0–P3 metin olarak yazılır; renk yalnız ipucudur", None)],
           "guide": "Sekme rehberi (adına tıklayın)", "guide_cols": ["#", "Sekme", "Ne içerir", "Grup"]},
    "en": {"band": "maya  ·  {brand} SEO analysis  ·  {sheet}", "brand_none": "site",
           "back": "← Cover", "source": "Source: {what}", "audit": "Maya Audit technical audit · crawl {date}",
           "audit_no_date": "Maya Audit technical audit · crawl date not recorded",
           "maya": "Maya export ({sets})", "computed": "computed from Maya's export",
           "method": "Maya Audit (method)", "plus": " + ",
           "title": "SEO and AI visibility analysis — {host}",
           "title_parts": {"audit": "technical audit", "data": "Search Console and AI citations", "rivals": "competitor comparison"},
           "review_done": "Reviewed by an SEO expert ({date})",
           "review_wait": "Waiting for the expert check: {open} items of \"Expert check\" have no decision",
           "review_none": "No item needs an expert check",
           "made": "Prepared on {date}. This is not when the metrics were measured; each source's own period is in the table below.",
           "scope": "Scope", "covered": "What is covered?", "not_covered": "What is not covered?",
           "covered_audit": "Maya Audit technical audit: {host}, crawl {date}; {read} pages read, {unread} known addresses not read.",
           "covered_data": " Maya export: {n} datasets ({sets}), each over its own period.",
           "not_assessed": "{n} parts the audit did not assess are on the \"Coverage\" sheet.",
           "no_data": "No Maya data attached: no Search Console or AI citation sheets in this file.",
           "no_ga4": "No GA4 data (visits, sessions and conversions not measured).",
           "no_inspection": "No Search Console URL inspection or index coverage report (not in Maya's export).",
           "no_estimate": "No traffic or conversion impact is estimated.",
           "files": "Source files", "file_cols": ["File", "Used", "Note"],
           "file_audit": "Maya Audit technical audit ({id})", "file_audit_used": "{n} sheets",
           "file_audit_note": "Crawl {date}; the engine version is the last row of \"Method\"",
           "file_rows": "{n} rows", "file_note": "Maya export · {dataset}",
           "periods": "Measurement periods (never summed or merged)", "period_cols": ["Data", "Period", "Sheet"],
           "period_audit": "Technical crawl", "period_none": "no period in the file (a snapshot)",
           "legend": "Colour legend",
           "legend_rows": [("Source data", "Values the audit or Maya's export measured (white)", None),
                           ("Computed / Maya text", "Fields Maya computed or wrote from the source", "computed"),
                           ("Expert / brand input", "Fields the SEO expert or the brand team fill in (empty)", "input"),
                           ("Green header", "Search Console and AI citation columns (Maya export)", "green"),
                           ("Priority label", "P0–P3 is written as text; the colour is only a hint", None)],
           "guide": "Sheet guide (click a name)", "guide_cols": ["#", "Sheet", "What it holds", "Group"]},
}


def lang_of(lang: str) -> str:
    return "tr" if lang == "tr" else "en"


def name(key: str, lang: str) -> str:
    return SHEETS[key][0 if lang_of(lang) == "tr" else 1]


def key_of(sheet_name: str) -> str | None:
    for k, names in SHEETS.items():
        if sheet_name in names:
            return k
    return None


def day(value: str | date | None, lang: str = "tr") -> str:
    """"2026-11-11" -> "11 Kasım 2026" ("11 November 2026")."""
    if not value:
        return ""
    try:
        d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value)
    return f"{d.day} {MONTHS[lang_of(lang)][d.month - 1]} {d.year}"


def period(start: str | None, end: str | None, lang: str = "tr") -> str:
    """"19 Ekim – 18 Kasım 2026"; the year once when both ends share it."""
    if not start or not end:
        return day(start or end, lang)
    a, b = day(start, lang), day(end, lang)
    if a[-4:] == b[-4:] and a[-4:].isdigit():
        a = a[:-5]
    return f"{a} – {b}"


def _host(report: dict | None) -> str:
    start = ((report or {}).get("crawl") or {}).get("start_url") or ((report or {}).get("crawl") or {}).get("origin") or ""
    return (urlsplit(start).hostname or "") if start else ""


def crawl_day(report: dict | None) -> str | None:
    crawl = (report or {}).get("crawl") or {}
    return str(crawl.get("started_at") or crawl.get("finished_at") or "")[:10] or None


def brand(report: dict | None, summary: dict | None) -> str:
    names = [n for n in (summary or {}).get("brand_names") or [] if n]
    if names:
        return str(names[0])
    host = _host(report)
    return host[4:] if host.startswith("www.") else host


def datasets(summary: dict | None) -> list[dict]:
    """The Maya export files read for this audit ({"dataset", "file", "period", "rows"}), meta left out."""
    return [d for d in (summary or {}).get("datasets") or [] if d.get("dataset") != "meta"]


def _needs(group: str) -> set[str]:
    from .maya_data import NEEDS
    return {name for need in NEEDS.get(group) or [] for name in need}


def sets_of(key: str, summary: dict | None) -> list[dict]:
    """The datasets a Maya sheet is made from, those present."""
    group = DATA_OF.get(key)
    wanted = _needs(group) if group else set()
    return [d for d in datasets(summary) if d.get("dataset") in wanted]


def _sets_text(found: list[dict], lang: str) -> str:
    w = W[lang_of(lang)]
    parts = [f"{d['dataset']} {period(*(d.get('period') or [None, None]), lang)}" if d.get("period") else d["dataset"]
             for d in found]
    return w["maya"].format(sets="; ".join(parts))


def source_line(key: str | None, report: dict | None, summary: dict | None, lang: str = "tr",
                computed: bool = False) -> str:
    """The band's "Kaynak: …" line: the audit with its crawl date, the Maya datasets with each one's own period."""
    w = W[lang_of(lang)]
    when = crawl_day(report)
    audit = w["audit"].format(date=day(when, lang)) if when else w["audit_no_date"]
    if key in ("how", "method", "competitor_notes", "source_map"):
        what = w["method"]
    elif key in DATA_OF:
        found = sets_of(key, summary)
        what = _sets_text(found, lang) if found else w["maya"].format(sets="—")
    elif key == "checklist" or key == "checklist_summary":
        gsc = [d for d in datasets(summary) if str(d.get("dataset", "")).startswith("gsc-")]
        what = audit + (w["plus"] + _sets_text(gsc, lang) if gsc else "")
    else:
        what = audit
    if computed:
        what += " · " + w["computed"]
    return w["source"].format(what=what)


def order(sheets: list[dict]) -> list[dict]:
    """The team's sheet order; a sheet the order does not know keeps its place after the known ones before it."""
    rank = {k: i for i, k in enumerate(ORDER)}
    keyed = []
    last = -1
    for i, s in enumerate(sheets):
        k = key_of(s["name"])
        last = rank[k] if k in rank else last
        keyed.append(((last, 0 if k in rank else 1, i), s))
    return [s for _, s in sorted(keyed, key=lambda x: x[0])]


def expert_rows(selection: dict) -> list[bool]:
    """One flag per row of "Uzman teyidi": whether the expert decision is filled (the owner's manual check of a finding
    waiting for confirmation)."""
    from .client_selection import manual
    confirmations = selection.get("_confirmations") or {}
    return [bool(any((manual(m, confirmations) or {}).get("result") for m in g.get("members") or []))
            for g in selection.get("confirm") or []]


def review_line(decided: list[bool], when: str | None, lang: str = "tr") -> str:
    """D5: "uzman değerlendirmesinden geçmiştir" only when every row of "Uzman teyidi" has an expert decision."""
    w = W[lang_of(lang)]
    if not decided:
        return w["review_none"]
    if all(decided):
        return w["review_done"].format(date=day(when, lang) if when else "—")
    return w["review_wait"].format(open=sum(1 for x in decided if not x))


def _last_decision(selection: dict) -> str | None:
    dates = [str(c.get("date") or "")[:10] for c in (selection.get("_confirmations") or {}).values() if isinstance(c, dict)]
    dates = [d for d in dates if d]
    return max(dates) if dates else None


def band(sheet_name: str, brand_name: str, source: str | None, lang: str = "tr", back: bool = True) -> list[list]:
    """The two band rows: the brand and the sheet; then "← Kapak" and the source line."""
    w = W[lang_of(lang)]
    cover = "'" + name("cover", lang).replace("'", "''") + "'!A1"
    second = ([{"text": w["back"], "location": cover}] if back else [""]) + ([source] if source else [])
    return [[w["band"].format(brand=brand_name or w["brand_none"], sheet=sheet_name)], second]


def cover(selection: dict, report: dict | None, summary: dict | None, made: list[dict], lang: str = "tr",
          now: datetime | None = None, decided: list[bool] | None = None) -> dict:
    """The "Kapak" sheet: title, review line, the date it was made, scope, source files, periods, legend, guide."""
    w, lg = W[lang_of(lang)], lang_of(lang)
    host = _host(report) or brand(report, summary)
    when = crawl_day(report)
    names = [m["name"] for m in made]
    keys = {key_of(n) for n in names}
    parts = [w["title_parts"]["audit"]]
    if keys & {"sc_summary", "sc_pages", "overview", "organic_summary", "ai_pages"}:
        parts.append(w["title_parts"]["data"])
    if keys & {"competitor_topics", "competitor_pages"}:
        parts.append(w["title_parts"]["rivals"])
    title = w["title"].format(host=host) + " · " + ", ".join(parts)
    review = review_line(expert_rows(selection) if decided is None else decided, _last_decision(selection), lang)
    made_on = (now or datetime.now(timezone.utc)).date()
    cov = selection.get("coverage") or {}
    sets = datasets(summary)
    rows: list[list] = []
    styles: dict[int, str] = {}

    def heading(text):
        styles[len(rows)] = "title"
        rows.append([text])

    def table_head(cols):
        styles[len(rows)] = "header"
        rows.append(list(cols))
    heading(w["scope"])
    covered = w["covered_audit"].format(host=host, date=day(when, lang) if when else "—",
                                        read=cov.get("pages_read") if cov.get("pages_read") is not None else "—",
                                        unread=cov.get("known_not_read") if cov.get("known_not_read") is not None else "—")
    if sets:
        covered += w["covered_data"].format(n=len(sets), sets=", ".join(d["dataset"] for d in sets))
    rows.append([w["covered"], covered])
    missing = []
    n_not = (selection.get("counts") or {}).get("not_assessed")
    if n_not:
        missing.append(w["not_assessed"].format(n=n_not))
    if not sets:
        missing.append(w["no_data"])
    if not any(d.get("dataset") == "ga4-traffic" for d in sets):
        missing.append(w["no_ga4"])
    missing += [w["no_inspection"], w["no_estimate"]]
    rows.append([w["not_covered"], " ".join(missing)])
    rows.append([""])
    heading(w["files"])
    table_head(w["file_cols"])
    audit_id = str(((report or {}).get("audit") or {}).get("id") or (report or {}).get("audit_id") or "")[:8]
    rows.append([w["file_audit"].format(id=audit_id or host), w["file_audit_used"].format(n=sum(
        1 for n in names if key_of(n) not in DATA_OF and key_of(n) not in ("sc_summary", "traffic", "sc_pages", "sc_queries",
                                                                         "sc_opportunities", "ai_pages"))),
                 w["file_audit_note"].format(date=day(when, lang) if when else "—")])
    for d in sets:
        rows.append([d.get("file") or d["dataset"], w["file_rows"].format(n=d["rows"]) if d.get("rows") is not None else "",
                     w["file_note"].format(dataset=d["dataset"])])
    rows.append([""])
    heading(w["periods"])
    table_head(w["period_cols"])
    audit_sheets = [n for n in names if key_of(n) in ("summary", "by_page", "by_finding", "findings", "urls", "templates",
                                                      "where", "redirect", "key_pages", "checklist")]
    rows.append([w["period_audit"], day(when, lang) if when else "—", ", ".join(audit_sheets)])
    for d in sets:
        using = [n for n in names if d in sets_of(key_of(n) or "", summary)]
        rows.append([d["dataset"], period(*d["period"], lang) if d.get("period") else w["period_none"], ", ".join(using)])
    rows.append([""])
    heading(w["legend"])
    colours: dict[int, str] = {}
    for label, text, style in w["legend_rows"]:
        if style:
            colours[len(rows)] = style
        rows.append([label, text])
    rows.append([""])
    heading(w["guide"])
    table_head(w["guide_cols"])
    sheet_list = [name("cover", lang)] + names
    for i, n in enumerate(sheet_list, 1):
        k = key_of(n)
        about = ABOUT.get(k or "")
        quoted = "'" + n.replace("'", "''") + "'!A1"
        rows.append([i, {"text": n, "location": quoted}, (about[1] if lg == "tr" else about[2]) if about else "",
                     GROUPS[lg][about[0]] if about else ""])
    return {"name": name("cover", lang), "header": [w["made"].format(date=day(made_on, lang))], "rows": rows,
            "widths": [34, 70, 60, 30], "frozen": False, "filter": False, "row_styles": styles,
            "_colours": colours, "band": [[title], [review]],
            "_counts": {"pages_read": (cov.get("pages_read"), name("cover", lang))} if cov.get("pages_read") is not None else {}}


def frame(made: list[dict], selection: dict, report: dict | None, summary: dict | None, lang: str = "tr",
          now: datetime | None = None) -> list[dict]:
    """The client Ek's sheets in the team's order, each with the Maya band, and "Kapak" first."""
    sheets = order([m for m in made if m["name"] not in INTERNAL])
    who = brand(report, summary)
    out = []
    for m in sheets:
        k = key_of(m["name"])
        out.append({**m, "band": band(m["name"], who, source_line(k, report, summary, lang, computed=bool(m.get("_computed"))), lang)})
    first = cover(selection, report, summary, out, lang, now)
    colours = first.pop("_colours")
    # the legend's colour cells: the label cell styled as the colour it explains
    first["row_styles"] = {**first["row_styles"], **{i: s for i, s in colours.items()}}
    return [first] + out
