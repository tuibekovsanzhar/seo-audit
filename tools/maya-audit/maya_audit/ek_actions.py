"""DECISIONS 376, phase 4: the client Ek's action sheets, built from the sheets already written (so every link points
at a real row): "Aksiyon planı" (T- per PDF card, S- per checklist item Search Console data turns into a problem, R-
per competitor topic), "Uzman teyidi" (every finding waiting for confirmation, every Search Console proposal that
changes a checklist result), "Yönetici özeti" (5-7 findings, each number taken from the row it links to), "Sayfa
grupları" and "Konum dizini". Expert and client columns stay empty with dropdowns (owner's D5); the PDF page of a
card is filled only when the PDF was printed with the Ek (D4). Turkish, as the team's file. Global for every audit.
"""
from __future__ import annotations

import re
from collections import OrderedDict, defaultdict
from urllib.parse import urlsplit

from .ek_frame import day, period

NAMES = {"actions": "Aksiyon planı", "expert": "Uzman teyidi", "exec": "Yönetici özeti", "groups": "Sayfa grupları",
         "locations": "Konum dizini"}
ACTION_COLS = ["Aksiyon kimliği", "Grup", "Konu", "Sorun türü", "Sorun veya fırsat (kaynak)", "Önerilen işlem",
               "İşlem metninin kaynağı", "İş açısından gerekçe", "Kaynak önceliği", "Öncelik türü", "Kaynak sorumlu",
               "Kaynak efor", "Kapsam (sayı)", "Kapsam birimi", "Benzersiz URL", "İlk 3 URL", "Tam liste",
               "Kaynak bulgu kimlikleri", "Kanıt", "Ek kanıt", "Ölçüm dönemi", "Gösterge (n<10)", "Çapraz bağlantı / not",
               "SEO değerlendirmesi", "Uzman notu", "Onaylanan öncelik", "Uygulama durumu", "Hedef tarih",
               "Doğrulama yöntemi", "Kitapçık sayfası (PDF)"]
INPUT_COLS = ("SEO değerlendirmesi", "Uzman notu", "Onaylanan öncelik", "Uygulama durumu", "Hedef tarih")
DROPDOWNS = {"SEO değerlendirmesi": ["Onaylandı", "Değiştirilmeli", "Reddedildi"],
             "Onaylanan öncelik": ["P0", "P1", "P2", "P3"],
             "Uygulama durumu": ["Başlamadı", "Sürüyor", "Tamamlandı", "Ertelendi"]}
EXPERT_COLS = ["Tür", "Kimlik", "Kontrol / madde", "Bulgu / kanıt (kaynak)", "Önem", "Güven sınıfı", "Teyit nedeni",
               "Araç sonucu", "SC eki önerilen sonuç", "Kaynakta ne yapılmalı", "Kanıt", "Kaynak satırı", "SEO değerlendirmesi",
               "Uzman notu"]
ITYPE = {"issue": "Sorun", "warning": "Kontrol edin", "opportunity": "Fırsat"}
SEV = {"S1": "Engelleyici", "S2": "Yüksek", "S3": "Orta", "S4": "Düşük", "Info": "Bilgi"}
CONF = {"measured": "Ölçülmüş", "estimated": "Tahmini", "inferred": "Çıkarım", "unverified": "Doğrulanmamış kontrol"}
FINDING_ID = re.compile(r"[A-Z]{2,5}-\d+-[0-9a-f]{6,}")
NO_PDF = "PDF oluşturulmadı"


def _q(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def _go(sheet: str, index: int, text: str | None = None) -> dict:
    """A link to body row `index` (0-based) of `sheet`; the text says the Excel row under the Maya band."""
    from .ek_frame import BAND_ROWS
    return {"text": text or f"{sheet} › satır {index + 2 + BAND_ROWS}", "location": f"{_q(sheet)}!A{index + 2}"}


class Book:
    """The sheets written so far, by name, with lookups by column."""

    def __init__(self, made: list[dict]):
        self.sheets = {m["name"]: m for m in made}

    def rows(self, name: str) -> list[list]:
        return list((self.sheets.get(name) or {}).get("rows") or [])

    def col(self, name: str, header: str) -> int | None:
        head = (self.sheets.get(name) or {}).get("header") or []
        return head.index(header) if header in head else None

    def first(self, name: str, header: str, test) -> int | None:
        c = self.col(name, header)
        if c is None:
            return None
        for i, r in enumerate(self.rows(name)):
            v = r[c] if c < len(r) else ""
            if test(v.get("text") if isinstance(v, dict) else v):
                return i
        return None

    def cell(self, name: str, i: int, header: str):
        c = self.col(name, header)
        r = self.rows(name)[i] if i is not None and i < len(self.rows(name)) else []
        v = r[c] if c is not None and c < len(r) else ""
        return v.get("text") if isinstance(v, dict) else v


def _card_rows(book: Book, n) -> list[int]:
    c = book.col("Bulgu bazında", "Kart")
    return [i for i, r in enumerate(book.rows("Bulgu bazında")) if c is not None and c < len(r) and str(r[c]) == str(n)]


def _urls_of(book: Book, idx: list[int]) -> list[str]:
    c = book.col("Bulgu bazında", "Sayfa")
    out = []
    for i in idx:
        v = book.rows("Bulgu bazında")[i][c] if c is not None else ""
        u = v.get("link") or v.get("text") if isinstance(v, dict) else v
        if u and u not in out:
            out.append(str(u))
    return out


def pdf_pages(pdf: bytes | None, todos: list[dict] | None) -> dict:
    """{card number: the PDF page its card starts on}, found by the card's title on a page after the first (page 1
    lists the top cards); {} without a PDF."""
    if not pdf or not todos:
        return {}
    try:
        import io
        from pypdf import PdfReader
        # the text reader puts spaces inside words ("ta ş ıyın"): compared without any whitespace
        pages = [re.sub(r"\s+", "", p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages]
    except Exception:  # noqa: BLE001  no reader or an unreadable file: the column says no PDF
        return {}
    out = {}
    for t in todos:
        title = re.sub(r"\s+", "", str(t.get("title") or ""))
        if not isinstance(t.get("n"), int) or not title:
            continue
        # a card's own heading: its number, its title, then its severity (the action table has the finding ID there)
        heading = re.compile(re.escape(f"{t['n']:02d}{title}") + r"(?:Engelleyici|Yüksek|Orta|Düşük|Bilgi|Not|Blocker|High|Medium|Low|Info|Note)")
        hit = next((i + 1 for i, text in enumerate(pages) if heading.search(text)), None)
        if hit:
            out[t["n"]] = hit
    return out


def _ids(values) -> list[str]:
    return [str(v) for v in values or [] if FINDING_ID.fullmatch(str(v))]


def actions(book: Book, todos: list[dict] | None, report: dict | None, summary: dict | None,
            pages: dict | None) -> list[dict]:
    """The actions, each a dict of the "Aksiyon planı" columns plus private links (`_rows`: its evidence rows)."""
    out = []
    when = str(((report or {}).get("crawl") or {}).get("started_at") or "")[:10]
    crawl = f"Teknik tarama {day(when)}" if when else "Teknik tarama"
    for t in [t for t in todos or [] if t.get("n") is not None]:
        idx = _card_rows(book, t["n"])
        urls = _urls_of(book, idx)
        ids = _ids(t.get("finding_ids"))
        full = next((i for f in ids for i in [book.first("Etkilenen adresler", "Bulgu kimliği", lambda v, f=f: v == f)] if i is not None), None)
        links = book.first("Bağlantı yerleri", "Kart", lambda v, n=t["n"]: str(v) == str(n))
        lead = book.first("Bulgular", "Bulgu kimliği", lambda v, f=ids[0] if ids else None: f is not None and v == f)
        problem = book.cell("Bulgu bazında", idx[0], "Sorun") if idx else ""
        fix = book.cell("Bulgu bazında", idx[0], "Ne yapılmalı") if idx else ""
        count = book.cell("Özet", book.first("Özet", "Kart", lambda v, n=t["n"]: str(v) == str(n)), "Etkilenen adres")
        out.append({
            "Aksiyon kimliği": f"T-{t['n']:02d}" if isinstance(t["n"], int) else f"T-{t['n']}", "Grup": "Teknik SEO",
            "Konu": t.get("title") or "", "Sorun türü": ITYPE.get(t.get("issue_type") or "", ""),
            "Sorun veya fırsat (kaynak)": problem or t.get("title") or "",
            "Önerilen işlem": fix or str(t.get("steps") or "").split("\n")[0],
            "İşlem metninin kaynağı": "Kaynak («Bulgu bazında» › Ne yapılmalı)" if fix else "Kaynak (PDF kartının ilk adımı)",
            "İş açısından gerekçe": t.get("why") or "", "Kaynak önceliği": t.get("p_level") or "",
            "Öncelik türü": "P0–P3 (Yöntem sekmesi)", "Kaynak sorumlu": t.get("owner") or "", "Kaynak efor": t.get("effort") or "",
            # the PDF's scope when it says more than a count ("2 sayfa (+88 sayfa: Orta)") is its own unit
            "Kapsam (sayı)": count if count != "" else len(urls),
            "Kapsam birimi": "etkilenen adres (Özet)" if count == "" or str(count).isdigit() else "PDF kartının kapsamı (Özet)",
            "Benzersiz URL": len(urls), "İlk 3 URL": "\n".join(urls[:3]),
            "Tam liste": _go("Etkilenen adresler", full) if full is not None else "",
            "Kaynak bulgu kimlikleri": "; ".join(ids), "Kanıt": _go("Bulgu bazında", idx[0]) if idx else
            (_go("Bulgular", lead) if lead is not None else ""),
            "Ek kanıt": _go("Bağlantı yerleri", links) if links is not None else "", "Ölçüm dönemi": crawl,
            "Gösterge (n<10)": "", "Çapraz bağlantı / not": "", "Doğrulama yöntemi": t.get("verify") or "",
            "Kitapçık sayfası (PDF)": (pages or {}).get(t["n"], NO_PDF if not pages else "PDF'te yok (yalnız Ek)"),
            "_rows": idx, "_urls": urls})
    # T- (Efsa's T-16): a checklist item the tool marks "Sorun" that no card covers is an action of its own
    t_next = max([t["n"] for t in todos or [] if isinstance(t.get("n"), int)], default=0)
    c_id0, c_res0, c_ref0 = (book.col("Kontrol listesi", h) for h in ("ID", "Sonuç", "Maya kuralı / kart"))
    for i, r in enumerate(book.rows("Kontrol listesi")):
        if None in (c_id0, c_res0) or c_res0 >= len(r) or r[c_res0] != "Sorun" or not str(r[c_id0]).startswith("SEO-"):
            continue
        ref = str(r[c_ref0]) if c_ref0 is not None and c_ref0 < len(r) else ""
        if ref.startswith(("Kart ", "Card ")):
            continue
        t_next += 1
        item, evidence = book.cell("Kontrol listesi", i, "Kontrol maddesi"), book.cell("Kontrol listesi", i, "Kanıt")
        group = book.cell("Kontrol listesi", i, "Grup")
        out.append({
            "Aksiyon kimliği": f"T-{t_next:02d}", "Grup": "Teknik SEO (karta bağlı değil)", "Konu": f"{item} · {group}",
            "Sorun türü": "Sorun", "Sorun veya fırsat (kaynak)": evidence,
            "Önerilen işlem": f"«{item}» maddesini kanıttaki değere göre düzeltin; kontrol listesinde «Geçti» olmalı",
            "İşlem metninin kaynağı": "Maya metni (kontrol listesi kanıtı)", "İş açısından gerekçe": "",
            "Kaynak önceliği": f"{book.cell('Kontrol listesi', i, 'Öncelik')} (kontrol listesi)",
            "Öncelik türü": "Kontrol listesi madde önceliği (P0–P3 hesabı değil)", "Kaynak sorumlu": "", "Kaynak efor": "",
            "Kapsam (sayı)": "", "Kapsam birimi": "site geneli ölçüm; adres listesi yok", "Benzersiz URL": "", "İlk 3 URL": "",
            "Tam liste": "", "Kaynak bulgu kimlikleri": str(r[c_id0]),  # a check's name is no finding ID (RG-28)
            "Kanıt": _go("Kontrol listesi", i), "Ek kanıt": "", "Ölçüm dönemi": crawl, "Gösterge (n<10)": "",
            "Çapraz bağlantı / not": "Kontrol listesinde «Sorun»; hiçbir karta bağlı değil" + (f" (Maya: {ref})" if ref else ""),
            "Doğrulama yöntemi": "Bir sonraki denetimde madde «Geçti» olmalı",
            "Kitapçık sayfası (PDF)": "Ek'e özgü (PDF'te yok)", "_rows": [], "_urls": []})
    # S-: a checklist item the Search Console data turns into a problem the tool did not see
    c_id, c_res, c_sc, c_ev = (book.col("Kontrol listesi", h) for h in ("ID", "Sonuç", "Search Console eki: önerilen sonuç",
                                                                        "Search Console kanıtı"))
    s = 0
    for i, r in enumerate(book.rows("Kontrol listesi")):
        if None in (c_id, c_res, c_sc) or c_sc >= len(r) or r[c_sc] != "Sorun" or r[c_res] == "Sorun":
            continue
        s += 1
        item = book.cell("Kontrol listesi", i, "Kontrol maddesi")
        evidence = r[c_ev] if c_ev is not None and c_ev < len(r) else ""
        opp = book.first("SC fırsatlar", "Fırsat türü (Maya)", lambda v: str(v).startswith("Yamyamlaşma")) if r[c_id] == "SEO-069" else None
        m = re.match(r"(?:\D*?)(\d[\d.]*) (?:sayfa|marka dışı|sorgu)", str(evidence))
        out.append({
            "Aksiyon kimliği": f"S-{s:02d}", "Grup": "Search Console eki", "Konu": item,
            "Sorun türü": "Search Console eki önerisi: Sorun", "Sorun veya fırsat (kaynak)": evidence,
            "Önerilen işlem": "Aynı sorguda yarışan sayfaların rolünü ayırın: biri hedef sayfa olsun, diğerleri ona bağlantı versin"
            if r[c_id] == "SEO-069" else "Kanıttaki sayfaların başlık ve açıklamasını aramaya göre yeniden yazın",
            "İşlem metninin kaynağı": "Maya metni (kontrol listesi maddesi)", "İş açısından gerekçe":
            "Aynı sorguda iki sayfa yarıştığında tıklar bölünür ve hiçbiri güçlü sıralanmaz" if r[c_id] == "SEO-069" else
            "Gösterim yüksekken tıklama düşükse sayfa arama sonucunda seçilmiyor",
            "Kaynak önceliği": f"{book.cell('Kontrol listesi', i, 'Öncelik')} (kontrol listesi)",
            "Öncelik türü": "Kontrol listesi madde önceliği (P0–P3 hesabı değil)", "Kaynak sorumlu": "SEO", "Kaynak efor": "",
            "Kapsam (sayı)": int(m.group(1).replace(".", "")) if m else "",
            "Kapsam birimi": ("marka dışı yamyamlaşma sorgusu" if r[c_id] == "SEO-069" else "sayfa (Search Console kanıtı)") if m else "",
            "Benzersiz URL": "", "İlk 3 URL": "", "Tam liste": _go("SC fırsatlar", opp) if opp is not None else "",
            "Kaynak bulgu kimlikleri": r[c_id], "Kanıt": _go("Kontrol listesi", i),
            "Ek kanıt": _go("SC fırsatlar", opp) if opp is not None else "",
            "Ölçüm dönemi": _sc_period(summary, r[c_id]), "Gösterge (n<10)": "", "Çapraz bağlantı / not": "",
            "Doğrulama yöntemi": "Bir sonraki Maya dışa aktarımında madde yeniden ölçülür; sonuç Geçti olmalı",
            "Kitapçık sayfası (PDF)": "Ek'e özgü (PDF'te yok)", "_rows": [], "_urls": []})
    # R-: a competitor topic, by the gap's rank
    for i, r in enumerate(book.rows("Rakip - Konu")):
        n = book.cell("Rakip - Konu", i, "Panel prompt (n)")
        topic = book.cell("Rakip - Konu", i, "Konu")
        if not topic:
            continue
        small = str(book.cell("Rakip - Konu", i, "Yalnız gösterge (n<10)")).strip()
        out.append({
            "Aksiyon kimliği": f"R-{len([a for a in out if a['Aksiyon kimliği'].startswith('R-')]) + 1:02d}",
            "Grup": "Rakip / içerik", "Konu": topic, "Sorun türü": "Rakip farkı",
            "Sorun veya fırsat (kaynak)": book.cell("Rakip - Konu", i, "İçgörü"),
            "Önerilen işlem": book.cell("Rakip - Konu", i, "Önerilen aksiyon"),
            "İşlem metninin kaynağı": "Kaynak («Rakip - Konu» › Önerilen aksiyon)",
            "İş açısından gerekçe": "AI cevaplarında bu konuda rakip kaynak gösteriliyor; marka sayfası cevabı vermiyorsa seçilmiyor",
            "Kaynak önceliği": f"Fark sırası {book.cell('Rakip - Konu', i, 'Öncelik')}",
            "Öncelik türü": "Rakip fark sırası (P0–P3 değil)", "Kaynak sorumlu": "", "Kaynak efor": "",
            "Kapsam (sayı)": n, "Kapsam birimi": "panel prompt (n)", "Benzersiz URL": "", "İlk 3 URL": "",
            "Tam liste": "", "Kaynak bulgu kimlikleri": f"Rakip - Konu satır {i + 1}", "Kanıt": _go("Rakip - Konu", i),
            "Ek kanıt": "", "Ölçüm dönemi": _ai_period(summary), "Gösterge (n<10)": "Evet (n<10, yalnız gösterge)" if small and small not in ("", "Hayır") else "",
            "Çapraz bağlantı / not": "", "Doğrulama yöntemi": "Bir sonraki dışa aktarımda konunun citation payı ve görünürlüğü karşılaştırılır",
            "Kitapçık sayfası (PDF)": "Ek'e özgü (PDF'te yok)", "_rows": [], "_urls": []})
    # cross links: actions that touch the same pages
    by_url = defaultdict(list)
    for a in out:
        for u in a["_urls"]:
            by_url[u].append(a["Aksiyon kimliği"])
    for a in out:
        others = sorted({x for u in a["_urls"] for x in by_url[u] if x != a["Aksiyon kimliği"]})
        if others:
            a["Çapraz bağlantı / not"] = "Aynı sayfalarda: " + ", ".join(others[:6]) + (" …" if len(others) > 6 else "")
    return out


def _sc_period(summary: dict | None, item: str) -> str:
    g = (summary or {}).get("gsc") or {}
    if item == "SEO-069" and (g.get("opportunities") or {}).get("period"):
        return f"{period(*g['opportunities']['period'])} (gsc-query-opportunities)"
    p = g.get("page_period") or g.get("day_period")
    return f"{period(*p)} ({g.get('page_source') or g.get('day_source')})" if p else ""


def _ai_period(summary: dict | None) -> str:
    p = ((summary or {}).get("ai") or {}).get("period")
    return f"Citation payı {period(*p)} (citation-mentions)" if p else ""


EMPTY = "Bu denetimde aksiyon yok: PDF kartı, Search Console önerisi ya da rakip konusu yok."


def action_sheet(acts: list[dict]) -> dict:
    if not acts:  # one line saying why, never an empty sheet (DECISIONS 321)
        return {"name": NAMES["actions"], "header": ["Not"], "rows": [[EMPTY]], "widths": [140]}
    rows = [[a.get(c, "") for c in ACTION_COLS] for a in acts]
    n = len(rows)
    col = {c: i for i, c in enumerate(ACTION_COLS)}
    from .xlsx import _col
    validations = [{"ref": f"{_col(col[c] + 1)}2:{_col(col[c] + 1)}{n + 1}", "list": v} for c, v in DROPDOWNS.items()] if n else []
    return {"name": NAMES["actions"], "header": ACTION_COLS, "rows": rows,
            "widths": [10, 16, 36, 18, 60, 60, 24, 50, 14, 24, 14, 10, 10, 22, 10, 60, 22, 30, 24, 24, 26, 14, 30,
                       16, 30, 14, 16, 14, 50, 14],
            "col_styles": {**{col[c]: "input" for c in INPUT_COLS}, col["İş açısından gerekçe"]: "computed",
                           col["Doğrulama yöntemi"]: "computed", col["Çapraz bağlantı / not"]: "computed"},
            "validations": validations}


def expert_groups(selection: dict) -> list[dict]:
    """The findings for the expert: those waiting for confirmation, and those an expert already decided (a confirmed
    finding leaves "Teyit edin"; its decision stays listed)."""
    from .client_selection import manual
    confirmations = selection.get("_confirmations") or {}
    waiting = list(selection.get("confirm") or [])
    seen = {id(g) for g in waiting}
    decided = [g for g in selection.get("groups") or [] if id(g) not in seen  # confirmed or rejected: both decisions
               and any(manual(m, confirmations) for m in g.get("members") or [])]
    return waiting + decided


def expert_sheet(book: Book, selection: dict) -> tuple[dict, list[bool]]:
    """Every finding waiting for confirmation, then every Search Console proposal that changes a checklist result;
    (the sheet, one flag per row: whether the expert decision is filled)."""
    from .client_selection import manual
    rows, decided = [], []
    confirmations = selection.get("_confirmations") or {}
    for g in expert_groups(selection):
        lead = (g.get("members") or [{}])[0]
        fid = lead.get("id") or ""
        at = book.first("Bulgu bazında", "Bulgu kimliği", lambda v, f=fid: v == f)
        row = book.first("Bulgular", "Bulgu kimliği", lambda v, f=fid: v == f)
        check = next((manual(m, confirmations) for m in g.get("members") or [] if manual(m, confirmations)), None) or {}
        word = {"confirmed": "Onaylandı", "rejected": "Reddedildi"}.get(check.get("result") or "", "")
        decided.append(bool(word))
        rows.append(["Bulgu (Teyit edin)", fid, lead.get("check_id") or "", book.cell("Bulgular", row, "Bulgu") if row is not None
                     else lead.get("title") or "", SEV.get(g.get("severity") or "", ""), CONF.get(g.get("confidence") or "", g.get("confidence") or ""),
                     _reason(g.get("confirm_reason")), "", "", book.cell("Bulgular", row, "Ne yapılmalı") if row is not None else "",
                     _go("Bulgu bazında", at) if at is not None else "", _go("Bulgular", row) if row is not None else "",
                     word, check.get("note") or ""])
    c_id, c_res, c_sc, c_ev = (book.col("Kontrol listesi", h) for h in ("ID", "Sonuç", "Search Console eki: önerilen sonuç",
                                                                        "Search Console kanıtı"))
    for i, r in enumerate(book.rows("Kontrol listesi")):
        if None in (c_id, c_res, c_sc) or c_sc >= len(r) or not r[c_sc] or r[c_sc] == r[c_res]:
            continue
        decided.append(False)
        rows.append(["Kontrol listesi SC eki önerisi", r[c_id], book.cell("Kontrol listesi", i, "Kontrol maddesi"),
                     r[c_ev] if c_ev is not None and c_ev < len(r) else "", "", "", "Search Console verisi aracın sonucunu değiştiriyor",
                     r[c_res], r[c_sc], "", _go("Kontrol listesi", i), _go("Kontrol listesi", i), "", ""])
    n = len(rows)
    validations = [{"ref": f"M2:M{n + 1}", "list": ["Onaylandı", "Değiştirilmeli", "Reddedildi"]}] if n else []
    if not rows:
        return {"name": NAMES["expert"], "header": ["Not"], "rows": [["Uzman teyidi gereken madde yok."]], "widths": [140]}, []
    return {"name": NAMES["expert"], "header": EXPERT_COLS, "rows": rows, "validations": validations,
            "widths": [24, 18, 30, 60, 10, 18, 30, 14, 16, 50, 22, 22, 16, 30], "col_styles": {12: "input", 13: "input"},
            "_decided": decided}, decided


def _reason(code) -> str:
    """The reason a finding waits for confirmation, in the Ek's words (never a code)."""
    from .client_appendix import WORDS
    return WORDS["tr"]["reason"].get(str(code or ""), str(code or "").replace("_", " "))


def _num(text) -> str | None:
    m = re.search(r"\d[\d.,]*", str(text or ""))
    return m.group(0) if m else None


def exec_sheet(book: Book, acts: list[dict], summary: dict | None, decided: list[bool], review: str) -> dict:
    """5-7 findings, each with its number, unit and period, its action and a link to the row the number comes from
    (`_claims`: what RG-29 compares)."""
    rows, claims, styles = [], [], {}
    tech = [a for a in acts if a["Aksiyon kimliği"].startswith("T-") and a["Sorun türü"] == "Sorun"][:4]
    for a in tech:
        claims.append((len(rows), str(a["Kapsam (sayı)"]), "Özet", "Kart", a["Aksiyon kimliği"][2:].lstrip("0")))
        unit = f" {a['Kapsam birimi']}" if str(a["Kapsam (sayı)"]).isdigit() else ""
        rows.append([len(rows) + 1, a["Konu"], f"Kart {a['Aksiyon kimliği'][2:].lstrip('0')} · {a['Kaynak önceliği']} · {a['Kapsam (sayı)']}{unit} · "
                     f"{a['Ölçüm dönemi']}", a["Aksiyon kimliği"], a["Kanıt"] or a["Tam liste"]])
    for a in [a for a in acts if a["Aksiyon kimliği"].startswith("S-")][:2]:
        rows.append([len(rows) + 1, a["Konu"], f"{a['Sorun veya fırsat (kaynak)']}", a["Aksiyon kimliği"], a["Kanıt"]])
    sc = book.sheets.get("Search Console özeti")
    if sc:
        i = next((k for k, r in enumerate(sc["rows"]) if r and r[0] == "Search Console'da tık alan ama denetimde okunmayan sayfa"), None)
        if i is not None:
            n = sc["rows"][i][1]
            claims.append((len(rows), str(n), "Search Console özeti", "Konu", sc["rows"][i][0]))
            rows.append([len(rows) + 1, "Search Console'da tık alan sayfaların bir kısmı denetimde okunmadı",
                         f"{n} sayfa (Search Console listesi, {_page_period(summary)}; denetim taraması)", "Açık konu 1",
                         _go("Search Console özeti", i)])
    for a in [a for a in acts if a["Aksiyon kimliği"].startswith("R-")][:1]:
        rows.append([len(rows) + 1, f"AI cevaplarında en büyük rakip farkı: {a['Konu']}", f"{a['Sorun veya fırsat (kaynak)']} · {a['Ölçüm dönemi']}",
                     a["Aksiyon kimliği"], a["Kanıt"]])
    totals = book.sheets.get("Kontrol listesi özeti")
    if totals and len(rows) < 7:
        at = next((k for k, r in enumerate(totals["rows"]) if r and r[0] == "Search Console eki sonrası (öneri)"), None)
        if at is not None:
            before, after = totals["rows"][at + 1], totals["rows"][at]
            rows.append([len(rows) + 1, "Search Console verisi kontrol listesi sonuçlarını değiştiriyor (uzman onayı bekliyor)",
                         "Geçti/Sorun/Veri eksik/İnceleme/Uygulanmaz: " + "/".join(str(x) for x in before[2:7]) + " → "
                         + "/".join(str(x) for x in after[2:7]) + f" ({before[1]} madde)", "Uzman teyidi",
                         _go("Kontrol listesi özeti", at)])
    rows = rows[:7]
    body = [list(r) for r in rows]
    styles[len(body)] = "title"
    body.append(["", "Açık konular (uzman onayı dışında kalan)"])
    styles[len(body)] = "header"
    body.append(["#", "Konu", "Neden karar gerekiyor", "Kim", "İlgili yer"])
    opens = []
    if sc:
        opens.append(["Bir sonraki denetimin sayfa kapsamı", "Search Console'da tık alan ve AI'ın alıntıladığı sayfaların bir kısmı "
                      "denetimde okunmadı; sayfa sınırı ve öncelik", "SEO uzmanı + Maya", "Search Console özeti, SC sayfaları"])
    if any(a["Aksiyon kimliği"].startswith("R-") for a in acts):
        opens.append(["Rakip aksiyonlarının sahibi ve takvimi", "Sorumlu, efor ve tarih kaynakta yok; Aksiyon planında boş",
                      "Marka ekibi", "Aksiyon planı R-"])
    opens.append(["Başarı takibi hedefleri", "Hedef değer ve tarih kaynakta yok; tahmin yazılmadı", "Marka ekibi + SEO uzmanı",
                  "Aksiyon planı › Hedef tarih"])
    for k, o in enumerate(opens, 1):
        body.append([k, *o])
    body.append([""])
    body.append(["Uzman onayı", review, "", "SEO uzmanı", "Aksiyon planı, Uzman teyidi"])
    units = []
    if (summary or {}).get("ai", {}).get("period"):
        units.append(["AI alıntı sayısı", f"{_ai_period(summary)}: markanın sayfalarının alıntılanma sayısı", "", "",
                      "AI alıntılanan sayfalar"])
    if (summary or {}).get("gsc"):
        units.append(["Search Console tık", "Tık sayısıdır; GA4 oturumu ya da ziyaretçi değildir; 28 günlük pencereler toplanmaz",
                      "", "", "Search Console özeti"])
    if units:
        body.append([""])
        styles[len(body)] = "title"
        body.append(["", "Ölçü birimleri birleştirilmez"])
        body += units
    return {"name": NAMES["exec"], "header": ["#", "Bulgu", "Kanıt (kaynak sayı, birim ve dönem)", "Aksiyon", "Kanıt sekmesi"],
            "rows": body, "widths": [6, 60, 70, 16, 30], "frozen": False, "filter": False, "row_styles": styles,
            "_claims": [(i, num, sheet, key_col, key) for i, num, sheet, key_col, key in claims]}


def _page_period(summary: dict | None) -> str:
    g = (summary or {}).get("gsc") or {}
    if g.get("page_kind") == "snapshot":
        return "son 28 gün"
    p = g.get("page_period")
    return period(*p) if p else "dönem belirtilmemiş"


def groups_sheet(book: Book, acts: list[dict]) -> dict | None:
    by_group: dict[str, OrderedDict] = defaultdict(OrderedDict)
    for a in acts:
        for u, i in zip(a["_urls"], a["_rows"]):
            path = urlsplit(u).path or "/"
            g = "/" + path.strip("/").split("/")[0] if path.strip("/") else "/"
            rec = by_group[g].setdefault(u, {"acts": [], "row": i})
            if a["Aksiyon kimliği"] not in rec["acts"]:
                rec["acts"].append(a["Aksiyon kimliği"])
    if not by_group:
        return None
    rows, styles = [], {}
    for g, pages in sorted(by_group.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        acts_in = sorted({x for p in pages.values() for x in p["acts"]})
        styles[len(rows)] = "title"
        rows.append([g, ", ".join(acts_in), len(pages)])
        for u, p in pages.items():
            rows.append(["", "", "", {"text": u, "link": u}, ", ".join(p["acts"]), _go("Bulgu bazında", p["row"])])
    return {"name": NAMES["groups"], "header": ["Sayfa grubu", "Bu gruptaki aksiyonlar", "Adres", "Sayfa", "Aksiyonlar", "Kanıt"],
            "rows": rows, "widths": [26, 40, 8, 70, 20, 28], "row_styles": styles}


def locations_sheet(acts: list[dict]) -> dict:
    if not acts:
        return {"name": NAMES["locations"], "header": ["Not"], "rows": [[EMPTY]], "widths": [140]}
    rows = []
    for k, a in enumerate(acts):
        span = ""
        if a["_rows"]:
            from .ek_frame import BAND_ROWS
            lo, hi = min(a["_rows"]) + 2 + BAND_ROWS, max(a["_rows"]) + 2 + BAND_ROWS
            span = {"text": f"Bulgu bazında › {lo}–{hi}" if hi > lo else f"Bulgu bazında › {lo}",
                    "location": f"'Bulgu bazında'!A{min(a['_rows']) + 2}"}
        rows.append([a["Aksiyon kimliği"], a["Konu"], _go(NAMES["actions"], k), span or a["Kanıt"], a["Ek kanıt"],
                     a["Kitapçık sayfası (PDF)"]])
    return {"name": NAMES["locations"], "header": ["Aksiyon", "Konu", "Aksiyon planı", "Kanıt (Excel)", "Ek kanıt (Excel)",
                                                   "Kitapçık sayfası (PDF)"], "rows": rows, "widths": [10, 50, 26, 30, 30, 16]}


def build(made: list[dict], selection: dict, todos: list[dict] | None, report: dict | None, summary: dict | None,
          pdf: bytes | None = None) -> tuple[list[dict], list[bool]]:
    """The five sheets (in the team's order: Yönetici özeti, Aksiyon planı, Uzman teyidi, Sayfa grupları, Konum
    dizini) and the expert decisions of "Uzman teyidi" (for Kapak's line)."""
    from .ek_frame import review_line
    book = Book(made)
    acts = actions(book, todos, report, summary, pdf_pages(pdf, todos))
    expert, decided = expert_sheet(book, selection)
    dates = [str(c.get("date") or "")[:10] for c in (selection.get("_confirmations") or {}).values() if isinstance(c, dict)]
    review = review_line(decided, max([d for d in dates if d], default=None), "tr")
    sheets = [exec_sheet(book, acts, summary, decided, review), action_sheet(acts), expert]
    if any(not a["Aksiyon kimliği"].startswith("T-") for a in acts) or sheets[0].get("_claims") and summary:
        # S- and R- rows, and the summary's Search Console lines, come from Maya's export: the band names its datasets
        used = [d["dataset"] for d in (summary or {}).get("datasets") or [] if d.get("dataset") != "meta"]
        for sh in sheets[:3]:
            sh["_datasets"] = used or None
    grp = groups_sheet(book, acts)
    if grp:
        sheets.append(grp)
    sheets.append(locations_sheet(acts))
    return sheets, decided
