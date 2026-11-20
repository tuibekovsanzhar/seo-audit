"""DECISIONS 376, phase 3: the client Ek's Search Console and AI sheets from Maya's export (`maya_data` summary) and the
audit: "Search Console özeti", "Trafiğe göre öncelik", "SC sayfaları", "SC sorgular", "SC fırsatlar", "AI alıntılanan
sayfalar", and the Search Console columns of "Sayfa bazında" and "Kilit sayfalar".

Rules (owner, from Efsa's final Enpara file): each source keeps its own period, never summed or merged; a 28-day
snapshot is never summed; a field the export does not hold says "Veri yok" and why, never 0 or a guess; a number Maya
computes where the team used the dashboard says "Maya dışa aktarımından hesaplandı"; without Maya data these sheets are
left out and Kapsam says so. Turkish, as the Maya sheets are. Global for every audit.
"""
from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlsplit

from .ek_frame import period
from .maya_data import _is_brand, page_url

NO = "Veri yok"
DEVICES = {"mobile": "mobil", "desktop": "masaüstü", "tablet": "tablet"}
COMPUTED = "Maya dışa aktarımından hesaplandı"
OPP_TYPES = {"cannibalization": "Yamyamlaşma: aynı sorguda birden çok sayfa",
             "high_impression_low_ctr": "Yüksek gösterim, düşük tıklama oranı",
             "striking_distance": "Yakın sıra: ilk sayfaya yakın"}
OPP_ORDER = ["cannibalization", "high_impression_low_ctr", "striking_distance"]
SEVERE = ("S1", "S2", "S3")  # Engelleyici, Yüksek, Orta
SEV_WORD = {"S1": "Engelleyici", "S2": "Yüksek", "S3": "Orta", "S4": "Düşük", "Info": "Bilgi"}
INTENT_WORDS = {"brand_search": "marka", "transactional": "işlem", "commercial": "ürün / ticari", "product": "ürün",
                "product_search": "ürün araması", "navigational": "yönlendirme", "informational": "bilgi",
                "discovery": "keşif", "tutorial": "öğretici", "definition": "tanım", "comparison": "karşılaştırma",
                "local": "yerel", "support": "destek"}


def intent_word(value) -> str:
    """Maya's intent label in Turkish; an unknown label with its underscores as spaces, never a code."""
    v = str(value or "").strip()
    return INTENT_WORDS.get(v, v.replace("_", " ")) if v else "sınıflanmadı"
STATUS = {"read_problem": "Okundu, sorun var", "read_ok": "Okundu, sorun yok", "unread_problem": "Okunmadı, sorun var",
          "unread": "Okunmadı"}
SC_COLS = ["SC tık (28 gün)", "SC gösterim (28 gün)", "SC CTR", "SC ort. sıra", "SC listede (ölçüm)", "SC ölçüm haftası",
           "AI alıntı sayısı", "Alıntılayan AI"]
NAMES = {"sc_summary": "Search Console özeti", "traffic": "Trafiğe göre öncelik", "sc_pages": "SC sayfaları",
         "sc_queries": "SC sorgular", "sc_opportunities": "SC fırsatlar", "ai_pages": "AI alıntılanan sayfalar"}


def _n(x) -> str:
    """12345 -> "12.345" (Turkish digit groups)."""
    if x is None:
        return NO
    if isinstance(x, float) and not x.is_integer():
        return f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{int(round(x)):,}".replace(",", ".")


def _pct(x) -> str:
    return NO if x is None else ("%" + f"{x * 100:.1f}".replace(".", ","))


def _dataset(summary: dict, name: str) -> dict | None:
    return next((d for d in summary.get("datasets") or [] if d.get("dataset") == name), None)


def _when(summary: dict, name: str, fallback=None) -> str:
    d = _dataset(summary, name)
    p = (d or {}).get("period") or fallback
    return period(*p, "tr") if p else "dosyada dönem yok"


class Data:
    """The summary and the audit, keyed the same way (Maya's page key on the audited origin)."""

    def __init__(self, summary: dict, selection: dict, rows: list[dict]):
        from .page_rows import page_table
        self.s, self.sel = summary, selection
        self.origin = summary.get("origin")
        self.gsc, self.ai = summary.get("gsc") or {}, summary.get("ai") or {}
        self.read = {self.key(u) for u in selection.get("_pages_read") or []}
        self.problems: dict[str, dict] = {}
        for p in page_table(rows):
            if p.get("url"):
                self.problems[self.key(p["url"])] = p
        top = self.gsc.get("top_pages") or {}
        self.weeks = len(top.get("weeks") or [])
        self.listed = {k: r.get("weeks_listed") for k, r in (top.get("rows") or {}).items()}
        self.week_of = {k: r.get("week") for k, r in (top.get("rows") or {}).items()}
        self.pages = {k: v for k, v in (self.gsc.get("pages") or {}).items() if isinstance(v, dict)}
        self.scores = (self.gsc.get("page_scores") or {}).get("rows") or {}
        self.cited = self.ai.get("pages") or {}

    def key(self, url: str) -> str:
        return page_url(url, self.origin) or url

    @property
    def snapshot(self) -> bool:
        return self.gsc.get("page_kind") == "snapshot"

    def metric_label(self) -> str:
        """What a page's clicks cover: the latest 28-day window, or the daily rows summed over their period."""
        if self.snapshot:
            return "28 gün"
        p = self.gsc.get("page_period")
        return period(*p, "tr") if p else "dönem belirtilmemiş"

    def status(self, key: str) -> str:
        read, problem = key in self.read, key in self.problems
        return STATUS["read_problem" if read and problem else "read_ok" if read else "unread_problem" if problem else "unread"]

    def problem_cells(self, key: str) -> list:
        p = self.problems.get(key)
        return ["; ".join(p["names"]), ", ".join(str(n) for n in p["cards"])] if p else ["", ""]

    def cites(self, key: str) -> tuple[int | None, str]:
        c = self.cited.get(key)
        if not c:
            return None, ""
        by = c.get("by_provider") or {}
        return sum(by.values()) or c.get("runs"), ", ".join(sorted(by))

    def is_brand(self, query: str) -> bool | None:
        flag = (((self.gsc.get("intents") or {}).get("rows") or {}).get(query) or {}).get("brand")
        return flag if flag is not None else _is_brand(query, self.s.get("brand_names") or [])


def _link(url: str) -> dict:
    return {"text": url, "link": url}


# ---------------------------------------------------------------- Search Console özeti

def summary_sheet(d: Data, pages_read: int | None) -> dict:
    s, g = d.s, d.gsc
    rows: list[list] = []
    styles: dict[int, str] = {}
    counts: dict[str, tuple] = {}

    def head(text):
        styles[len(rows)] = "title"
        rows.append([text])
    head("Kaynaklar (her biri kendi döneminde; toplanmaz, birleştirilmez)")
    for ds in s.get("datasets") or []:
        if ds.get("dataset") == "meta":
            continue
        rows.append([ds["dataset"], period(*ds["period"], "tr") if ds.get("period") else "dosyada dönem yok (anlık görüntü)",
                     f"{_n(ds['rows'])} satır · {ds.get('file') or ''}" if ds.get("rows") is not None else ds.get("file") or ""])
    if not any(ds.get("dataset") == "ga4-traffic" for ds in s.get("datasets") or []):
        rows.append(["GA4", NO, "Maya dışa aktarımında GA4 veri seti yok: ziyaret, oturum ve dönüşüm ölçülmedi"])
    rows.append([""])
    totals = g.get("totals") or {}
    src = g.get("day_source") or "günlük veri"
    blocks = (("last28", "Site geneli: son 28 gün"), ("whole", "Site geneli: dosyanın tüm dönemi"))
    if (totals.get("whole") or {}).get("days", 99) <= 28:  # the file holds 28 days or fewer: one block, not two alike
        blocks = (("whole", f"Site geneli: dosyanın tüm dönemi ({totals['whole']['days']} gün)"),)
    for key, title in blocks:
        t = totals.get(key)
        head(f"{title} ({COMPUTED})")
        if not t:
            rows.append(["Tık, gösterim, CTR, sıra", NO, "Günlük Search Console verisi eklenmedi (gsc-daily-stats ya da "
                                                        "gsc-search-performance)"])
            continue
        when = f"{src}, {period(*t['period'], 'tr')} ({t['days']} gün); günlük satırlar toplandı"
        rows += [["Tık", _n(t["clicks"]), when], ["Gösterim", _n(t["impressions"]), when],
                 ["Ort. CTR", _pct(t["ctr"]), "tık / gösterim"], ["Ort. sıra", _n(t["position"]) if t["position"] else NO,
                                                                  "gösterimle ağırlıklı"]]
    rows.append([""])
    head("Kırılımlar")
    devices = g.get("devices") or {}
    sp = _when(s, "gsc-search-performance")
    if devices:
        total = sum(v.get("clicks") or 0 for v in devices.values()) or 1
        rows.append(["Cihaz", " · ".join(f"{DEVICES.get(k.lower(), k.lower())} {_n(v.get('clicks'))} tık (%{round(100 * (v.get('clicks') or 0) / total)}, "
                                         f"CTR {_pct((v.get('clicks') or 0) / v['impressions'] if v.get('impressions') else None)})"
                                         for k, v in sorted(devices.items(), key=lambda kv: -(kv[1].get("clicks") or 0))),
                     f"gsc-search-performance, {sp}; {COMPUTED}"])
    else:
        rows.append(["Cihaz", NO, "Dışa aktarımda cihaz kırılımı yok (gsc-search-performance eklenmedi)"])
    countries = g.get("countries") or {}
    if countries:
        rows.append(["Ülke", " · ".join(f"{k.upper()} {_n(v.get('clicks'))} tık" for k, v in list(countries.items())[:6]),
                     f"gsc-search-performance, {sp}"])
    else:
        rows.append(["Ülke", NO, "Dışa aktarımda ülke kırılımı yok (gsc-search-performance eklenmedi)"])
    intents = (g.get("intents") or {}).get("rows") or {}
    if intents:
        by = Counter(intent_word(v.get("intent")) for v in intents.values())
        n = sum(by.values())
        rows.append(["Sorgu niyeti", " · ".join(f"{k} %{round(100 * c / n)}" for k, c in by.most_common()),
                     f"gsc-query-intents: dosyadaki {_n(n)} sorgunun sayısına göre; {COMPUTED}"])
    else:
        rows.append(["Sorgu niyeti", NO, "Dışa aktarımda sorgu niyeti yok (gsc-query-intents eklenmedi)"])
    brand = g.get("brand") or {}
    if brand.get("brand") or brand.get("non_brand"):
        b, nb = brand.get("brand") or {}, brand.get("non_brand") or {}
        allc = (b.get("clicks") or 0) + (nb.get("clicks") or 0)
        rows.append(["Marka sorgularının tık payı", _pct((b.get("clicks") or 0) / allc) if allc else NO,
                     f"{g.get('brand_source')}, {_when(s, str(g.get('brand_source')))}; marka adları: "
                     + ", ".join(s.get("brand_names") or []) + f"; {COMPUTED}"])
    aio = g.get("aio") or {}
    if aio.get("columns") and aio.get("days"):
        rows.append(["AI Overview", f"{_n(aio['impressions'])} gösterim, {_n(aio['clicks'])} tık",
                     f"gsc-daily-stats, {period(*aio['period'], 'tr')} ({aio['days']} gün)"])
    elif aio.get("columns"):
        rows.append(["AI Overview", NO, "gsc-daily-stats'ın AI Overview sütunları bu dönemde boş: «AI Overview'da "
                                        "görünmüyoruz» anlamına gelmez"])
    else:
        rows.append(["AI Overview", NO, "Dışa aktarımda AI Overview sütunu yok"])
    rows.append(["İndeks sağlığı (URL denetimi)", NO, "Search Console URL denetimi ve dizin kapsamı raporu Maya "
                                                       "dışa aktarımında yok"])
    rows.append([""])
    head("Denetim × Search Console")
    rows.append(["Denetimde okunan sayfa", _n(pages_read) if pages_read is not None else NO, "Maya Audit taraması"])
    if pages_read is not None:
        counts["pages_read"] = (pages_read, NAMES["sc_summary"])
    if d.pages:
        in_list = sum(1 for k in d.read if k in d.pages)
        unread = sorted(k for k, v in d.pages.items() if (v.get("clicks") or 0) > 0 and k not in d.read)
        rows.append(["… bunlardan Search Console listesinde olan", _n(in_list),
                     f"{g.get('page_source')}: listede olmayan sayfa ölçülmemiş sayılır, «tık yok» değildir"])
        rows.append(["Search Console'da tık alan ama denetimde okunmayan sayfa", _n(len(unread)),
                     "«SC sayfaları» › «Denetimdeki durumu» = Okunmadı"])
        counts["sc_unread"] = (len(unread), NAMES["sc_summary"])
        total = sum(v.get("clicks") or 0 for v in d.pages.values())
        severe = sum(v.get("clicks") or 0 for k, v in d.pages.items() if (d.problems.get(k) or {}).get("worst") in SEVERE)
        rows.append(["Orta ya da daha ciddi sorunlu sayfaların tık payı",
                     f"{_n(severe)} / {_n(total)} ({_pct(severe / total) if total else NO})",
                     f"{g.get('page_source')} ({d.metric_label()}); {COMPUTED}"])
    opps = (g.get("opportunities") or {}).get("rows") or []
    if opps:
        canni = [o for o in opps if o["type"] == "cannibalization" and not d.is_brand(o["query"])]
        rows.append(["Marka dışı yamyamlaşma sorgusu", _n(len(canni)),
                     "gsc-query-opportunities; marka sorgularında çok sayfa çıkması doğaldır"])
        counts["canni_nonbrand"] = (len(canni), NAMES["sc_summary"])
    if d.cited:
        unread_cited = sum(1 for k in d.cited if k not in d.read)
        rows.append(["AI'ın alıntıladığı sayfa", _n(len(d.cited)), f"{_n(unread_cited)} tanesi denetimde okunmadı"])
        counts["ai_pages"] = (len(d.cited), NAMES["sc_summary"])
    notes = []
    if g.get("top_pages") or g.get("top_queries"):
        notes.append(["Haftalık satırlar 28 günlüktür", "Toplanmaz", "Her hafta alınmış satır 28 günlük bir penceredir; "
                      "sayfa ya da sorgu başına en son satır kullanıldı (toplanırsa aynı tık birkaç kez sayılır)"])
    if any(o["type"] == "cannibalization" and not o.get("clicks") for o in opps):
        notes.append(["Yamyamlaşma satırlarında tık ve sıra", NO, "Maya bu satırlarda tık ve sırayı doldurmuyor: "
                      "gösterim ve yarışan sayfa sayısı kullanıldı"])
    if notes:
        rows.append([""])
        head("Dikkat")
        rows += notes
    return {"name": NAMES["sc_summary"], "header": ["Konu", "Değer", "Not"], "rows": rows, "widths": [44, 60, 90],
            "frozen": False, "filter": False, "row_styles": styles, "_counts": counts, "_computed": True,
            "_datasets": [x["dataset"] for x in s.get("datasets") or [] if x.get("dataset") != "meta"]}


# ---------------------------------------------------------------- page sheets

def _whole(x):
    """A count as a whole number (12.0 -> 12); None stays None."""
    return int(round(x)) if isinstance(x, (int, float)) else x


def _metrics(d: Data, key: str) -> list:
    m = d.pages.get(key) or {}
    return [_whole(m.get("clicks")) if m else None, _whole(m.get("impressions")) if m else None,
            m.get("ctr") if m else None, m.get("position") if m else None]


def _cells(values: list) -> list:
    return ["" if v is None else v for v in values]


def traffic_sheet(d: Data) -> dict | None:
    """Pages read with at least one problem, by Search Console clicks."""
    if not d.pages:
        return None
    label = d.metric_label()
    rows = []
    for key, p in d.problems.items():
        if key not in d.read:
            continue
        cites, _ = d.cites(key)
        rows.append([_link(key), *_cells(_metrics(d, key)), cites if cites is not None else "",
                     p["importance"] if isinstance(p.get("importance"), (int, float)) else "", p["problems"],
                     SEV_WORD.get(p["worst"], "") if p.get("worst") else "", "; ".join(p["names"]),
                     ", ".join(str(n) for n in p["cards"])])
    rows.sort(key=lambda r: (-(r[1] or 0) if isinstance(r[1], (int, float)) else 1, -(r[2] or 0) if isinstance(r[2], (int, float)) else 1))
    header = ["Sayfa", f"SC tık ({label})", f"SC gösterim ({label})", "SC CTR", "SC ort. sıra", "AI alıntı sayısı",
              "Önem puanı (0-100)", "Sorun sayısı", "En yüksek önem", "Sorunlar", "Kartlar"]
    return {"name": NAMES["traffic"], "header": header, "rows": rows, "widths": [70, 12, 14, 9, 10, 12, 12, 10, 14, 70, 10],
            "header_styles": {i: "green" for i in range(1, 6)},
            "_datasets": [str(d.gsc.get("page_source")), "citation-mentions"] if d.cited else [str(d.gsc.get("page_source"))]}


def pages_sheet(d: Data) -> dict | None:
    """Every page Search Console lists, with its audit status."""
    if not d.pages:
        return None
    label = d.metric_label()
    rows = []
    for key in sorted(d.pages, key=lambda k: (-(d.pages[k].get("clicks") or 0), -(d.pages[k].get("impressions") or 0), k)):
        sc = d.scores.get(key) or {}
        cites, _ = d.cites(key)
        listed = f"{d.listed[key]} / {d.weeks}" if d.weeks and d.listed.get(key) else ""
        rows.append([_link(key), *_cells(_metrics(d, key)), listed, d.week_of.get(key) or "",
                     _whole(sc.get("query_count")) if sc.get("query_count") is not None else "",
                     _whole(sc.get("authority_score")) if sc.get("authority_score") is not None else "",
                     cites if cites is not None else "", d.status(key), *d.problem_cells(key)])
    header = ["Sayfa", f"Tık ({label})", f"Gösterim ({label})", "CTR", "Ort. sıra", "Listede (ölçüm)", "Ölçüm haftası",
              "Sorgu sayısı (Maya skoru)", "Otorite skoru (Maya)", "AI alıntı sayısı", "Denetimdeki durumu", "Sorunlar", "Kartlar"]
    used = [str(d.gsc.get("page_source"))] + (["gsc-page-scores"] if d.scores else []) + (["citation-mentions"] if d.cited else [])
    unread = sum(1 for r in rows if r[10] in (STATUS["unread"], STATUS["unread_problem"]) and isinstance(r[1], (int, float)) and r[1] > 0)
    return {"name": NAMES["sc_pages"], "header": header, "rows": rows, "widths": [70, 12, 14, 9, 10, 12, 12, 14, 12, 12, 20, 60, 10],
            "header_styles": {i: "green" for i in range(1, 10)}, "_datasets": used,
            "_counts": {"sc_unread": (unread, NAMES["sc_pages"])}}


def queries_sheet(d: Data) -> dict | None:
    top = (d.gsc.get("top_queries") or {}).get("rows") or {}
    intents = (d.gsc.get("intents") or {}).get("rows") or {}
    if not top and not intents:
        return None
    weeks = len((d.gsc.get("top_queries") or {}).get("weeks") or [])

    def brand_word(q):
        b = d.is_brand(q)
        return "evet" if b else "hayır"
    if top:
        rows = [[q, _whole(r["clicks"]), _whole(r["impressions"]), "" if r.get("ctr") is None else r["ctr"],
                 "" if r.get("position") is None else r["position"], f"{r.get('weeks_listed')} / {weeks}" if weeks else "",
                 r.get("week") or "", intent_word((intents.get(q) or {}).get("intent")),
                 brand_word(q)] for q, r in top.items()]
        header = ["Sorgu", "Tık (28 gün)", "Gösterim (28 gün)", "CTR", "Ort. sıra", "Listede (ölçüm)", "Ölçüm haftası",
                  "Niyet (Maya)", "Marka mı?"]
        used = ["gsc-top-queries"] + (["gsc-query-intents"] if intents else [])
        styles = {i: "green" for i in range(1, 7)}
    else:
        # only the intent file: no clicks or impressions per query in the export
        rows = [[q, intent_word(v.get("intent")), brand_word(q),
                 "" if v.get("confidence") is None else v["confidence"]] for q, v in intents.items()]
        rows.insert(0, ["Tık ve gösterim: Veri yok (gsc-top-queries eklenmedi); yalnız Maya'nın niyet sınıflaması", "", "", ""])
        header = ["Sorgu", "Niyet (Maya)", "Marka mı?", "Güven (Maya)"]
        used, styles = ["gsc-query-intents"], {}
    return {"name": NAMES["sc_queries"], "header": header, "rows": rows, "widths": [50, 12, 14, 9, 10, 12, 12, 18, 10],
            "header_styles": styles, "_datasets": used, "title_rows": 0 if top else 1}


def opportunities_sheet(d: Data) -> dict | None:
    opps = (d.gsc.get("opportunities") or {}).get("rows") or []
    if not opps:
        return None
    rows = []
    for o in sorted(opps, key=lambda o: (bool(d.is_brand(o["query"])), OPP_ORDER.index(o["type"]) if o["type"] in OPP_ORDER else 9,
                                         -(o["impressions"] or 0))):
        keys = [d.key(u) for u in o["pages"]]
        with_problem = [k for k in keys if k in d.problems]
        rows.append([o["query"], "Marka" if d.is_brand(o["query"]) else "Marka dışı", OPP_TYPES.get(o["type"] or "", o["type"] or ""),
                     _whole(o["impressions"]), len(keys) if keys else "", "\n".join(keys),
                     "" if o.get("score") is None else o["score"],
                     ", ".join(urlsplit(k).path or "/" for k in with_problem),
                     period(*o["period"], "tr") if o.get("period") else ""])
    canni = sum(1 for r in rows if r[1] == "Marka dışı" and r[2] == OPP_TYPES["cannibalization"])
    return {"name": NAMES["sc_opportunities"], "header": ["Sorgu", "Marka / marka dışı", "Fırsat türü (Maya)", "Gösterim",
                                                          "Yarışan sayfa sayısı", "Sayfalar", "Fırsat skoru (Maya)",
                                                          "Bu sayfalardan denetimde sorunlu olanlar", "Dönem"],
            "rows": rows, "widths": [40, 14, 34, 12, 12, 70, 12, 60, 24], "header_styles": {3: "green", 4: "green", 6: "green"},
            "_datasets": ["gsc-query-opportunities"], "_counts": {"canni_nonbrand": (canni, NAMES["sc_opportunities"])}}


def ai_sheet(d: Data) -> dict | None:
    if not d.cited:
        return None
    label = d.metric_label()
    rows = []
    for key, c in sorted(d.cited.items(), key=lambda kv: (-sum((kv[1].get("by_provider") or {}).values()), kv[0])):
        cites, who = d.cites(key)
        clicks = (d.pages.get(key) or {}).get("clicks") if d.pages else None
        rows.append([_link(key), cites, who, c.get("prompts"), "" if clicks is None else _whole(clicks), d.status(key),
                     *d.problem_cells(key)])
    header = ["Sayfa (izleme parametreleri ve #:~:text temizlendi)", "AI alıntı sayısı", "Alıntılayan AI", "Kaç soruda",
              f"SC tık ({label})", "Denetimdeki durumu", "Sorunlar", "Kartlar"]
    return {"name": NAMES["ai_pages"], "header": header, "rows": rows, "widths": [70, 12, 40, 10, 12, 20, 60, 10],
            "header_styles": {1: "green", 2: "green", 3: "green", 4: "green"},
            "_datasets": ["citation-mentions"] + ([str(d.gsc.get("page_source"))] if d.pages else []),
            "_counts": {"ai_pages": (len(rows), NAMES["ai_pages"])}}


# ---------------------------------------------------------------- columns on the audit's own sheets

def add_columns(sheet: dict, d: Data, url_col: int = 0) -> dict:
    """"Sayfa bazında" and "Kilit sayfalar" with the Search Console and AI columns (green headers)."""
    if not (d.pages or d.cited) or sheet.get("header") in (None, ["Not"], ["Note"]):
        return sheet
    label = d.metric_label()
    header = list(sheet["header"]) + [c.replace("28 gün", label) for c in SC_COLS]
    rows = []
    for r in sheet["rows"]:
        cell = r[url_col] if url_col < len(r) else ""
        url = cell.get("text") if isinstance(cell, dict) else cell
        key = d.key(str(url)) if url else ""
        m = _metrics(d, key) if key in d.pages else [None] * 4
        cites, who = d.cites(key)
        listed = f"{d.listed[key]} / {d.weeks}" if d.weeks and d.listed.get(key) else ""
        rows.append(list(r) + [*_cells(m), listed, d.week_of.get(key) or "", "" if cites is None else cites, who])
    first = len(sheet["header"])
    used = ([str(d.gsc.get("page_source"))] if d.pages else []) + (["citation-mentions"] if d.cited else [])
    return {**sheet, "header": header, "rows": rows, "widths": list(sheet.get("widths") or []) + [12, 14, 9, 10, 12, 12, 12, 30],
            "header_styles": {**(sheet.get("header_styles") or {}), **{first + i: "green" for i in range(len(SC_COLS))}},
            "_datasets": list(sheet.get("_datasets") or []) + used}


def build(summary: dict | None, selection: dict, rows: list[dict]) -> dict[str, Any]:
    """{"sheets": the six sheets that have data, "data": the Data (for the column add-ons), "missing": Kapsam lines}."""
    if not summary or not ((summary.get("gsc") or {}) or (summary.get("ai") or {}).get("pages")):
        return {"sheets": [], "data": None, "missing": []}
    d = Data(summary, selection, rows)
    pages_read = (selection.get("coverage") or {}).get("pages_read")
    made = [summary_sheet(d, pages_read), traffic_sheet(d), pages_sheet(d), queries_sheet(d), opportunities_sheet(d), ai_sheet(d)]
    missing = []
    for sheet, (name, why) in zip(made[1:], (("traffic", "sayfa bazında Search Console verisi yok"),
                                              ("sc_pages", "sayfa bazında Search Console verisi yok"),
                                              ("sc_queries", "gsc-top-queries ve gsc-query-intents yok"),
                                              ("sc_opportunities", "gsc-query-opportunities yok"),
                                              ("ai_pages", "citation-mentions'ta markanın sayfası yok"))):
        if sheet is None:
            missing.append(f"«{NAMES[name]}» sekmesi yok: Maya verisinde {why}")
    return {"sheets": [m for m in made if m is not None], "data": d, "missing": missing}
