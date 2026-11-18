"""The appendix's sheets from Maya data (DECISIONS 352), in the style of the team's Enpara file (Efsa's "0", "B1", "B2",
"C1", "C2", "D1" and "Z" sheets): "Genel durum", "Organik×AI - Özet", "Organik×AI - Segmentler", "Sayfa detay",
"Rakip - Konu" and "Rakip - Sayfa yapısı", with their lines for "Nasıl okunur", "Kapsam" and "Yöntem".

Made from `maya_data.prepare`'s summary and the audit's own crawl (statuses, redirects, page types, the saved page
evidence). Sends no request: pages the crawl did not read are measured only when `enrich` fetched them before.
Thresholds come from the site's own distribution (quartiles), never fixed numbers. A sheet whose datasets are missing
is left out and Kapsam says which dataset was missing. Correlation is not causation, and the sheets say so.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Callable
from urllib.parse import urlsplit

from .maya_data import is_generic, page_url

SEGMENTS = {  # code: (definition, what to do) — Efsa's B1, in her order
    "3": ("İkisinde de güçlü (koru)", "Koru; değişiklikten önce ölç"),
    "1": ("Organikte güçlü, AI'da az", "Answer-first giriş, sayısal bilgi, soru-cevap"),
    "1b": ("Organikte güçlü, AI'da az — panel bu konuyu sormuyor", "Önce Maya paneline prompt ekle"),
    "4": ("Gösterim yüksek, tık ve citation düşük", "Başlığın vaadini sayfada cevapla; title/meta"),
    "2": ("AI'da kaynak, organikte zayıf", "Title/meta + iç bağlantı"),
    "2b": ("AI'da kaynak, GSC listesinde yok (organik ölçülmedi)", "Search Console'da ayrıca bak"),
    "5": ("AI yönlenen / ölü adresi kaynak gösteriyor", "301 + hedef sayfa aynı soruyu cevaplasın"),
    "6": ("Organik trafik almış sayfa artık 404", "301 ile yeni adrese yönlendir"),
    "0": ("AI hedefi değil (form / hukuki / yardımcı)", "Aksiyon yok"),
}
SEGMENT_ACTION = {
    "3": "İki kanalda da güçlü — koruyun: içerik ve oranlar güncel kalsın, büyük yapısal değişiklikten önce ölçün.",
    "1": "Organik trafik var ama AI az kaynak gösteriyor: girişe doğrudan cevap, sayısal bilgi ve soru-cevap bölümü ekleyin.",
    "1b": "Organikte güçlü; Maya paneli bu konuyu az soruyor: önce bu konu için prompt ekleyin, sonra AI görünürlüğünü ölçün.",
    "4": "Çok gösterim alıyor ama tıklanmıyor ve AI kaynak göstermiyor: başlığın vaadini sayfada cevaplayın, title/meta'yı düzeltin.",
    "2": "AI kaynak gösteriyor ama organikte zayıf: title/meta'yı aramaya göre yazın, ilgili sayfalardan iç bağlantı verin.",
    "2b": "AI kaynak gösteriyor; Search Console listesinde yok: organik durumu Search Console'da ayrıca kontrol edin.",
    "5": "AI yönlenen ya da çalışmayan bir adresi kaynak gösteriyor: 301 ile güncel sayfaya yönlendirin, o sayfa aynı soruyu cevaplasın.",
    "6": "Organik trafik almış sayfa artık 404: 301 ile en yakın güncel sayfaya yönlendirin.",
    "0": "AI'ın kaynak göstermesi beklenmeyen sayfa (form, hukuki metin, yardımcı sayfa): aksiyon yok.",
}
ORDER = ["3", "1", "1b", "4", "2", "2b", "5", "6", "0"]
# Page type weights for the importance score (Efsa's "Z" sheet).
WEIGHTS = {"home": 20, "product": 20, "fee": 15, "support": 10, "blog": 10, "campaign": 5, "other": 0, "legal": -20,
           "form": -30}
TYPE_WORDS = {"home": "ana sayfa", "product": "ürün", "fee": "ücret", "support": "destek", "blog": "blog / rehber",
              "campaign": "kampanya", "other": "diğer", "legal": "hukuki", "form": "form / başvuru"}
_FORM = re.compile(r"basvur|application|apply|signup|sign-up|register|kayit|uye-ol|musteri-ol|login|giris|form|checkout|sepet|"
                   r"cart|account|hesabim", re.I)
_LEGAL = re.compile(r"kvkk|gizlilik|privacy|cerez|cookie|sozlesme|aydinlatma|yasal|legal|politika|policy|terms|kosul|"
                    r"imprint|bilgilendirme-formu", re.I)
_FEE = re.compile(r"ucret|fee|fiyat|price|pricing|tarife|komisyon", re.I)
_SUPPORT = re.compile(r"(^|/)(sss|faq|yardim|help|destek|support|iletisim|contact)(/|$|-)", re.I)
_BLOG = re.compile(r"(^|/)(blog|blogs|bilgi-bankasi|rehber|guide|haber|news|makale|articles?)(/|$)", re.I)
_CAMPAIGN = re.compile(r"kampanya|campaign|firsat|promo|indirim|offer", re.I)
SOCIAL = ("instagram.com", "youtube.com", "facebook.com", "x.com", "twitter.com", "tiktok.com", "linkedin.com",
          "reddit.com", "wikipedia.org", "eksisozluk.com", "sikayetvar.com", "google.com", "apple.com", "play.google.com")
_NUMBER = re.compile(r"(?<![\w.,])\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\s?(?:%|TL|₺|\$|€|gün|ay|yıl|saat|dk|bin|milyon)?(?![\w])")
_DATE = re.compile(r"\b(20\d\d)\b|\b\d{1,2}[./]\d{1,2}[./]20\d\d\b|güncelle|updated|son güncelleme", re.I)
CORRELATION = "Korelasyon nedensellik değildir: organik ve AI metriklerinin birlikte hareketi tek başına etki kanıtı değildir."
SHEETS = {"overview": "Genel durum", "summary": "Organik×AI - Özet", "segments": "Organik×AI - Segmentler",
          "detail": "Sayfa detay", "topics": "Rakip - Konu", "structure": "Rakip - Sayfa yapısı"}
MAX_DETAIL = 40
MAX_EXTERNAL_PER_TOPIC = 3


def _round(x, n=4):
    return round(x, n) if isinstance(x, (int, float)) else x


def quartiles(values: list[float]) -> tuple[float, float]:
    """(median, upper quartile) of the values, the site's own distribution."""
    v = sorted(values)
    if not v:
        return 0.0, 0.0
    q3 = v[min(len(v) - 1, int(round(0.75 * (len(v) - 1))))]
    return float(median(v)), float(q3)


def _rank(values: dict[str, float]) -> dict[str, float]:
    """Percentile rank (0-1) of each value among the positive ones; 0 for none."""
    pos = sorted(v for v in values.values() if v > 0)
    if not pos:
        return {k: 0.0 for k in values}
    out = {}
    for k, v in values.items():
        if v <= 0:
            out[k] = 0.0
        else:
            out[k] = sum(1 for x in pos if x <= v) / len(pos)
    return out


# ---------------------------------------------------------------- the crawl, keyed like the Maya data


def alias_key(url: str) -> str:
    from .checks.team_rules import alias_key as key
    return key(url)


class Crawl:
    """The audit's own pages: status, redirect, page type, canonical and the saved evidence (main text, JSON-LD)."""

    def __init__(self, report: dict, evidence_dir: Path | None = None, fetched: dict | None = None,
                 records: dict[str, dict] | None = None, profile: str | None = None):
        crawl = report.get("crawl") or {}
        # DECISIONS 357: the page records the appendix's own sheets use (the selection's, typed for the business
        # profile), so a page has one type in every sheet; the saved crawl's own grouping only without them.
        self.records = {page_url(u, crawl.get("origin") or crawl.get("start_url") or "") or u: g
                        for u, g in (records or {}).items() if isinstance(g, dict)}
        self.profile = profile
        self.origin = crawl.get("origin") or crawl.get("start_url") or ""
        self.pages: dict[str, dict] = {}
        self.canonical: dict[str, str] = {}
        for p in crawl.get("pages") or []:
            if not isinstance(p, dict) or not p.get("url"):
                continue
            u = page_url(p["url"], self.origin)
            if u:
                self.pages[u] = p
                for c in (p.get("analysis") or {}).get("canonicals") or []:
                    cu = page_url(c, self.origin)
                    if cu and cu != u and alias_key(cu) != alias_key(u):
                        self.canonical[u] = cu
        self.evidence: dict[str, dict] = {}
        if evidence_dir and Path(evidence_dir).is_dir():
            for f in sorted(Path(evidence_dir).glob("*.json")):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                u = page_url(d.get("url") or "", self.origin)
                if u:
                    self.evidence[u] = d
        self.fetched = fetched or {}

    def main_of(self, url: str) -> str:
        """The main address of a page: its canonical when the crawl read it with one, else its own address; the
        alias forms of one page (/anasayfa, /default.aspx, a trailing slash, letter case) are one key."""
        target = self.canonical.get(url, url)
        return target

    def status(self, url: str) -> tuple[int | None, str | None]:
        p = self.pages.get(url)
        if not p:
            return None, None
        return p.get("status"), p.get("redirect_location")

    def record(self, url: str) -> dict:
        return self.records.get(url) or (self.pages.get(url) or {}).get("grouping") or {}

    def type_word(self, url: str) -> str:
        """DECISIONS 357: the page's type in the words of "Sayfa bazında" (the profile's type when one applies)."""
        from .client_appendix import WORDS
        from .page_rows import page_kind_of, type_word
        g = self.record(url)
        if not g:
            # a page this audit did not read: typed from its address with the same profile, as Akıllı sampling does
            from . import business_types as bt
            from .sampling import pre_type
            kind, _ = pre_type(bt.profile(self.profile), url)
            if kind == "file":
                return "dosya (adresten)"
            if kind == "other" and self.kind(url) in ("legal", "form"):
                kind = "policy" if self.kind(url) == "legal" else "utility"
            return (type_word(kind, "tr", self.profile, WORDS["tr"]["page_type"]) or "—") + " (adresten)"
        return type_word(page_kind_of(g), "tr", self.profile, WORDS["tr"]["page_type"]) or "—"

    def kind(self, url: str) -> str:
        """The page kind for the importance weight: the page's type (the profile's when one applies), else the address."""
        g = self.record(url)
        generic, biz = g.get("page_type"), str(g.get("business_page_type") or "")
        path = urlsplit(url).path.lower()
        if generic == "home" or path in ("", "/"):
            return "home"
        if generic == "utility" or _FORM.search(path):
            return "form"
        if generic == "policy" or _LEGAL.search(path):
            return "legal"
        if re.search(r"fee|pricing|ucret", biz) or _FEE.search(path):
            return "fee"
        if re.search(r"support|help|faq|contact|sales|guide", biz) and "blog" not in biz or _SUPPORT.search(path):
            return "support"
        if generic == "blog_article" or re.search(r"blog", biz) or _BLOG.search(path):
            return "blog"
        if re.search(r"campaign", biz) or _CAMPAIGN.search(path):
            return "campaign"
        if generic in ("product", "category") or biz and biz not in ("other", "home", "utility", "policy"):
            return "product"
        return "other"

    def measure(self, url: str) -> dict | None:
        """What "Sayfa detay" and "Rakip - Sayfa yapısı" show of a page: from the crawl's record and saved evidence,
        else from a page `enrich` fetched; None when the page was not read."""
        if url in self.fetched:
            return self.fetched[url]
        p = self.pages.get(url)
        if not p or not isinstance(p.get("status"), int) or not 200 <= p["status"] < 300 or not p.get("analysis"):
            return None
        a = p["analysis"]
        ev = self.evidence.get(url) or {}
        return measure_parts(a.get("title"), a.get("meta") or [], a.get("headings") or ev.get("headings") or [],
                             ev.get("main_text"), ev.get("json_ld_blocks"), a.get("tables") or [],
                             (a.get("structured_data") or {}).get("types") or [], a.get("time_elements") or [])


def measure_parts(title, meta, headings, main_text, jsonld_blocks, tables, types, times) -> dict:
    desc = next((m.get("content") or "" for m in meta or [] if isinstance(m, dict) and (m.get("name") or "").lower() == "description"), None)
    h1 = next((h.get("text") or "" for h in headings if isinstance(h, dict) and h.get("level") == 1), "")
    h2 = [h.get("text") or "" for h in headings if isinstance(h, dict) and h.get("level") == 2]
    lines = [x.strip() for x in (main_text or "").split("\n") if x.strip()] if main_text is not None else None
    words = sum(len(x.split()) for x in lines) if lines is not None else None
    first = next((x for x in lines or [] if len(x.split()) >= 6), None)
    numbers = len(_NUMBER.findall(main_text or "")) if main_text is not None else None
    faq = sum(len(re.findall(r'"@type"\s*:\s*"Question"', b)) for b in jsonld_blocks or []) if jsonld_blocks is not None else None
    big_tables = sum(1 for t in tables if isinstance(t, dict) and (t.get("rows") or 0) >= 3) if tables else 0
    dated = bool(times) or bool(_DATE.search(main_text or "")) or any("dateModified" in b or "datePublished" in b
                                                                       for b in jsonld_blocks or [])
    return {"title": title or "", "meta_chars": len(desc) if desc is not None else None, "h1": h1, "h2": h2,
            "question_h2": sum(1 for x in h2 if x.strip().endswith("?")), "words": words,
            "js_heavy": words is not None and words < 150, "tables": big_tables, "faq_questions": faq,
            "numbers": numbers, "dated": dated, "types": sorted(set(types or [])), "first": first}


def measure_html(html: str) -> dict:
    """The same measures of a page fetched by `enrich` (its HTML, read with the engine's own analysis)."""
    from .analysis import analyze_html
    a = analyze_html(html)
    text = "\n".join(a.get("_content_blocks") or a.get("_text_blocks") or [])
    return measure_parts(a.get("title"), a.get("meta") or [], a.get("headings") or [], text, a.get("_jsonld_raw") or [],
                         a.get("tables") or [], (a.get("structured_data") or {}).get("types") or [], a.get("time_elements") or [])


# ---------------------------------------------------------------- pages: GSC × AI × crawl


def _topics(summary: dict) -> dict[str, str | None]:
    """{prompt id: topic}: Maya's prompt label that is a topic (meta.json; a plain name or a "cluster:" value), else the
    visibility topic whose name words the prompt holds (most hits; one topic per prompt, the first on a tie), else
    "Konu dışı etiketler" when the prompt has only labels that are not topics (DECISIONS 358), else None."""
    from .maya_data import OFF_TOPIC, topic_of
    info = (summary.get("ai") or {}).get("prompts") or {}
    vis = [t["topic"] for t in ((summary.get("visibility") or {}).get("topics") or [])]
    words = {t: [w for w in re.split(r"[_\-\s/]+", _fold(t)) if len(w) > 2] for t in vis}
    out = {}
    for pid, p in info.items():
        topic = topic_of(p["topic"]) if p.get("topic") else None  # a summary saved before 358 kept any first label
        if topic:
            out[pid] = topic
            continue
        if p.get("labels") or p.get("topic"):  # labelled, but with no topic among its labels
            out[pid] = OFF_TOPIC
            continue
        text = _fold(p.get("text") or "")
        best = max(((sum(1 for w in ws if w in text), -i, t) for i, (t, ws) in enumerate(words.items())), default=None)
        out[pid] = best[2] if best and best[0] > 0 else None
    return out


def _fold(text: str) -> str:
    table = str.maketrans("çğıöşüâîûÇĞİÖŞÜ", "cgiosuaiucgiosu")
    return (text or "").translate(table).lower()


def pages(summary: dict, crawl: Crawl) -> tuple[list[dict], dict]:
    """One row per page (duplicates merged into the main page), with its segment and importance; and the thresholds."""
    gsc = (summary.get("gsc") or {}).get("pages") or {}
    weekly = ((summary.get("gsc") or {}).get("weekly_sample") or {}).get("clicks") or {}
    ai = (summary.get("ai") or {}).get("pages") or {}
    topics = _topics(summary)
    topic_n = Counter(t for pid, t in topics.items() if t)
    rows: dict[str, dict] = {}
    keyed: dict[str, str] = {}

    def clean(url: str) -> bool:
        """The page's own address: its path is the alias key's (no /anasayfa, /default.aspx, trailing form)."""
        return alias_key(url).split("/", 1)[-1] == urlsplit(url).path.strip("/").lower() and not urlsplit(url).query

    def row_for(url: str) -> dict:
        main = crawl.main_of(url)
        key = alias_key(main)
        if key not in keyed:
            keyed[key] = main
            rows[main] = {"url": main, "duplicates": [], "dup_runs": 0, "gsc": None, "prompts": set(), "runs": 0,
                          "by_provider": Counter()}
        elif clean(main) and not clean(keyed[key]):
            # the clean address met after a duplicate becomes the main row; the duplicate is listed under it
            old = keyed[key]
            row = rows.pop(old)
            row["duplicates"] = [old] + [d for d in row["duplicates"] if d != main]
            row["url"] = main
            rows[main] = row
            keyed[key] = main
        main = keyed[key]
        if url != main and url not in rows[main]["duplicates"]:
            rows[main]["duplicates"].append(url)
        return rows[main]
    for u, g in gsc.items():
        if not (urlsplit(u).hostname or "").lower().removeprefix("www.").endswith(summary["domain"]):
            continue
        r = row_for(u)
        if r["gsc"] is None or u == r["url"]:
            r["gsc"] = g  # the main address's own row; a duplicate's figures are not added (they are another address)
    for u, a in ai.items():
        r = row_for(u)
        r["prompts"].update(a.get("prompt_ids") or [])
        r["runs"] += a.get("runs") or 0
        r["by_provider"].update(a.get("by_provider") or {})
        if u != r["url"]:
            r["dup_runs"] += a.get("runs") or 0
    measured = [r for r in rows.values() if r["gsc"]]
    clicks = [r["gsc"]["clicks"] for r in measured]
    impr = [r["gsc"]["impressions"] for r in measured]
    cited = [len(r["prompts"]) for r in rows.values() if r["prompts"]]
    org_med, org_q3 = quartiles(clicks)
    ai_med, ai_q3 = quartiles(cited)
    _, impr_q3 = quartiles(impr)
    th = {"org_strong": org_q3, "org_weak": org_med, "ai_strong": ai_q3, "ai_few": ai_med, "impr_high": impr_q3,
          "gsc_pages": len(measured), "ai_pages": len(cited)}
    impr_rank = _rank({u: (r["gsc"] or {}).get("impressions") or 0 for u, r in rows.items()})
    ai_rank = _rank({u: len(r["prompts"]) for u, r in rows.items()})
    for u, r in rows.items():
        kind = crawl.kind(u)
        status, location = crawl.status(u)
        page_topics = Counter(topics.get(p) for p in r["prompts"] if topics.get(p))
        topic = page_topics.most_common(1)[0][0] if page_topics else None
        n_prompts = len(r["prompts"])
        g = r["gsc"]
        r.update(kind=kind, status=status, location=location, topic=topic, topic_prompts=topic_n.get(topic, 0) if topic else 0,
                 n_prompts=n_prompts, weekly=weekly.get(u),
                 importance=max(0, min(100, round(40 * impr_rank[u] + 40 * ai_rank[u] + WEIGHTS[kind]))))
        seg = None
        dead = isinstance(status, int) and (300 <= status < 400 or status >= 400)
        if WEIGHTS[kind] <= -20:
            seg = "0"
        elif g and g["clicks"] > 0 and status in (404, 410):
            seg = "6"
        elif n_prompts and dead:
            seg = "5"
        elif g:
            if g["clicks"] >= org_q3 and n_prompts >= ai_q3 and n_prompts:
                seg = "3"
            elif g["clicks"] >= org_q3 and n_prompts < ai_med:
                seg = "1b" if r["topic_prompts"] < 10 else "1"
            elif g["impressions"] >= impr_q3 and g["clicks"] < org_med and n_prompts < ai_med:
                seg = "4"
            elif n_prompts >= max(1, ai_med) and g["clicks"] < org_med:
                seg = "2"  # "AI'da kaynak": cited in at least the median number of prompts of the cited pages
        elif n_prompts >= max(1, ai_med):
            seg = "2b"
        r["segment"] = seg
    out = sorted(rows.values(), key=lambda r: (-r["importance"], r["url"]))
    return out, th


# ---------------------------------------------------------------- sheets


def _pct(x):
    return round(x, 4) if isinstance(x, (int, float)) else ""


def _short(url: str) -> str:
    p = urlsplit(url)
    return (p.hostname or "").removeprefix("www.") + (p.path if p.path != "/" else "") + (f"?{p.query}" if p.query else "")


def _link(url: str, text: str | None = None) -> dict:
    return {"text": text or url, "link": url}


def overview_rows(summary: dict) -> list[list]:
    gsc, ai = summary.get("gsc") or {}, summary.get("ai") or {}
    rows: list[list] = [[f"Genel durum — {summary['domain']} (Maya export)"]]
    if gsc.get("monthly"):
        p = gsc.get("day_period") or ["", ""]
        rows += [[], [f"Organik performans (Search Console, aylık) — {gsc.get('day_source')}, {p[0]} – {p[1]}; günlük satırlar toplandı"],
                 ["Ay toplamları gün sayısı farklıysa hafta içi günlük ortalamayla karşılaştırın."],
                 ["Ay", "Gün", "Tık", "Gösterim", "Sıra", "Hafta içi günlük tık", "Hafta içi günlük gösterim"]]
        rows += [[m["month"], m["days"], m["clicks"], m["impressions"], m["position"], m["weekday_clicks"], m["weekday_impressions"]]
                 for m in gsc["monthly"]]
        if gsc.get("weeks"):
            rows += [[], ["Eşdeğer hafta içi (Pzt–Cum) karşılaştırması"], ["Hafta", "Tık", "Gösterim", "Ort. sıra"]]
            rows += [[w["week"], w["clicks"], w["impressions"], w["position"]] for w in gsc["weeks"][-6:]]
    if gsc.get("brand"):
        b, nb = gsc["brand"].get("brand") or {}, gsc["brand"].get("non_brand") or {}
        rows += [[], [f"Marka ve marka dışı sorgular — {gsc.get('brand_source')}"], ["Sorgu", "Tık", "Gösterim"],
                 ["Marka", round(b.get("clicks", 0)), round(b.get("impressions", 0))],
                 ["Marka dışı", round(nb.get("clicks", 0)), round(nb.get("impressions", 0))]]
    for key, title in (("devices", "Cihaz"), ("countries", "Ülke")):
        if gsc.get(key):
            rows += [[], [f"{title} kırılımı — gsc-search-performance"], [title, "Tık", "Gösterim"]]
            rows += [[k, round(v.get("clicks", 0)), round(v.get("impressions", 0))] for k, v in gsc[key].items()]
    if ai.get("monthly"):
        p = ai.get("period") or ["", ""]
        rows += [[], [f"AI cevaplarında {summary['domain']} kaynak payı (aylık) — citation-mentions, {p[0]} – {p[1]}"],
                 ["Ay", "Satır", summary["domain"], "Pay"]]
        rows += [[m["month"], m["rows"], m["brand_rows"], _pct(m["brand_rows"] / m["rows"]) if m["rows"] else ""] for m in ai["monthly"]]
        months = [m["month"] for m in ai["monthly"]]
        sov = ai.get("sov") or {}
        rows += [[], ["Sağlayıcı bazında: marka payı (SoV, aylık; result-items) ve citation payı (citation-mentions)"],
                 ["Sağlayıcı"] + months + ["Citation payı"]]
        for prov, c in sorted((ai.get("providers") or {}).items(), key=lambda kv: -kv[1]["rows"]):
            rows.append([prov] + [_pct(sov.get(f"{prov}|{m}")) if sov else "—" for m in months]
                        + [_pct(c["brand_rows"] / c["rows"]) if c["rows"] else ""])
    vis = (summary.get("visibility") or {}).get("topics")
    if vis:
        rows += [[], ["Konu bazında marka anılma oranı (%) — marka ve lider rakip (topic-visibility-snapshots); büyük fark = öncelikli konu"],
                 ["Konu", "Marka (ilk hafta)", "Marka (son hafta)", "Lider rakip", "Rakip (ilk hafta)", "Rakip (son hafta)", "Fark (son)"]]
        for t in sorted(vis, key=lambda t: -(t["gap"] if t["gap"] is not None else -999)):
            rows.append([t["topic"], t["brand_first"], t["brand_last"], t["leader"] or "—", t["leader_first"] if t["leader"] else "",
                         t["leader_last"] if t["leader"] else "", t["gap"] if t["gap"] is not None else ""])
    if ai.get("top_domains"):
        total = len(ai.get("prompts") or {}) or ai.get("prompts_cited") or 0
        rows += [[], ["AI cevaplarında en çok kaynak gösterilen diğer alan adları (citation = AI cevabındaki kaynak; backlink değildir)"],
                 ["Alan adı", f"Kaynak gösterildiği prompt ({total} içinde)"]]
        rows += [[d, n] for d, n in ai["top_domains"][:15]]
    rows += [[], [CORRELATION]]
    return rows


def segment_sheets(summary: dict, crawl: Crawl) -> tuple[dict, dict, list[dict], dict]:
    rows, th = pages(summary, crawl)
    seg_rows = [r for r in rows if r["segment"]]
    seg_rows.sort(key=lambda r: (ORDER.index(r["segment"]), -r["importance"], r["url"]))
    providers = [p for p, _ in sorted(((summary.get("ai") or {}).get("providers") or {}).items(), key=lambda kv: -kv[1]["rows"])][:5]
    header = ["Önem puanı", "Sayfa", "Segment", "Sayfa türü", "Konu", "GSC'de ölçüldü mü", "GSC tık", "GSC gösterim", "CTR",
              "Ort. sıra", "GSC haftalık tık (örneklem)", "AI prompt", "AI koşu"] + [f"{p} koşu" for p in providers] + [
              "Konudaki panel prompt sayısı", "Kopya adresler (citation onlara da sayıldı)", "Tarama durumu", "Ne yapılmalı", "Seg. kodu"]
    body = []
    first_row: dict[str, int] = {}
    for i, r in enumerate(seg_rows, 2):
        g = r["gsc"] or {}
        first_row.setdefault(r["segment"], i)
        body.append([r["importance"], _link(r["url"]), SEGMENTS[r["segment"]][0], crawl.type_word(r["url"]), r["topic"] or "—",
                     "Evet" if r["gsc"] else "Hayır (ölçülmedi)", round(g["clicks"]) if g else "", round(g["impressions"]) if g else "",
                     _pct(g.get("ctr")) if g else "", g.get("position") if g else "", round(r["weekly"]) if r["weekly"] else "",
                     r["n_prompts"], r["runs"]] + [r["by_provider"].get(p, 0) for p in providers] + [
                     r["topic_prompts"] or "", "; ".join(_short(d) for d in r["duplicates"]),
                     _status_words(r["status"], r["location"]), SEGMENT_ACTION[r["segment"]], r["segment"]])
    counts = Counter(r["segment"] for r in seg_rows)
    where = "'" + SHEETS["segments"] + "'"
    summary_rows = [[code, SEGMENTS[code][0], counts.get(code, 0), SEGMENTS[code][1],
                     {"text": "Satırlara git →", "location": f"{where}!A{first_row[code]}"} if code in first_row else ""]
                    for code in ORDER]
    summary_rows += [[], ["Eşikler (sitenin kendi dağılımından)",
                          f"organikte güçlü = tık ≥ {round(th['org_strong'])} (üst çeyrek); organikte zayıf = tık < {round(th['org_weak'])} "
                          f"(medyan altı); AI'da güçlü = ≥ {round(th['ai_strong'])} prompt; AI'da az = < {round(th['ai_few'])} prompt; "
                          f"gösterim yüksek = ≥ {round(th['impr_high'])}"],
                     ["Segment dışı sayfalar", sum(1 for r in rows if not r["segment"])], [], [CORRELATION]]
    sheet_summary = {"name": SHEETS["summary"], "header": ["Segment", "Tanım", "Sayfa sayısı", "Ne yapılmalı", "Satırlara git"],
                     "rows": summary_rows, "widths": [10, 60, 14, 50, 16]}
    sheet_segments = {"name": SHEETS["segments"], "header": header, "rows": body,
                      "widths": [10, 60, 34, 14, 22, 14, 10, 12, 8, 8, 12, 9, 9] + [10] * len(providers) + [12, 40, 18, 60, 8]}
    return sheet_summary, sheet_segments, rows, th


def _status_words(status, location) -> str:
    if status is None:
        return "taranmadı"
    if 300 <= status < 400:
        return f"{status} → {_short(location or '')}"
    return str(status)


def detail_sheet(summary: dict, crawl: Crawl, rows: list[dict]) -> dict:
    ai = summary.get("ai") or {}
    prompt_urls = ai.get("prompt_urls") or {}
    top = [r for r in rows if r["segment"] and r["segment"] != "0"][:MAX_DETAIL]
    header = ["Önem puanı", "Sayfa", "Segment", "Sayfa türü", "Konu", "GSC gösterim", "GSC tık", "CTR", "Ort. sıra", "AI prompt",
              "Konudaki panel prompt", "Title", "Meta (kr.)", "H1", "H2 sayısı", "H2'ler (ilk 8)", "Ana metin (kelime)", "Tablo (≥3 satır)",
              "FAQ şema soru", "Sayısal değer", "Tarih sinyali", "Şema", "İlk cümle",
              "Aynı prompt'larda kaynak gösterilen rakip sayfalar (koşu payı)", "Bulgular", "Ne yapılmalı"]
    body = []
    for r in top:
        m = crawl.measure(r["url"])
        g = r["gsc"] or {}
        others: Counter = Counter()
        for pid in r["prompts"]:
            others.update(prompt_urls.get(pid) or {})
        total = sum(others.values())
        competitors = "; ".join(f"{_short(u)} ({round(100 * n / total)}%)" for u, n in others.most_common(3)) if total else ""
        if m is None or m.get("error"):
            cells = ["okunmadı" if m is None else "alınamadı"] + [""] * 11
        else:
            cells = [m["title"], m["meta_chars"] if m["meta_chars"] is not None else "yok", m["h1"], len(m["h2"]),
                     " | ".join(m["h2"][:8]), _words(m), m["tables"], _blank(m["faq_questions"]), _blank(m["numbers"]),
                     "Evet" if m["dated"] else "Hayır", ", ".join(m["types"]), m["first"] or ""]
        body.append([r["importance"], _link(r["url"]), SEGMENTS[r["segment"]][0], crawl.type_word(r["url"]), r["topic"] or "—",
                     round(g["impressions"]) if g else "", round(g["clicks"]) if g else "", _pct(g.get("ctr")) if g else "",
                     g.get("position") if g else "", r["n_prompts"], r["topic_prompts"] or ""] + cells + [
                     competitors, "\n".join(findings(m)) if m and not m.get("error") else "", SEGMENT_ACTION[r["segment"]]])
    return {"name": SHEETS["detail"], "header": header, "rows": body,
            "widths": [10, 50, 30, 12, 20, 12, 10, 8, 8, 9, 12, 40, 10, 30, 9, 60, 14, 10, 10, 10, 10, 40, 60, 60, 50, 60]}


def _words(m: dict):
    if m.get("words") is None:
        return ""
    return f"{m['words']} (JS ağırlıklı — karşılaştırılamaz)" if m.get("js_heavy") else m["words"]


def _blank(v):
    return "" if v is None else v


def findings(m: dict | None) -> list[str]:
    """Rule-based notes on a page (the team's D1 "Bulgular")."""
    if not m:
        return []
    out = []
    if not m.get("faq_questions") and not m.get("question_h2"):
        out.append("• Soru-cevap bölümü yok")
    if len(m.get("title") or "") < 30:
        out.append(f"• Title kısa ({len(m.get('title') or '')} kr.)")
    elif len(m.get("title") or "") > 65:
        out.append(f"• Title uzun ({len(m.get('title') or '')} kr.)")
    if m.get("meta_chars") is None:
        out.append("• Meta açıklaması yok")
    if not m.get("h2"):
        out.append("• H2 yok")
    if m.get("numbers") is not None and m["numbers"] < 3:
        out.append("• Oran / ücret / limit bilgisi metinde neredeyse yok")
    if not m.get("tables"):
        out.append("• HTML tablo yok")
    if not m.get("dated"):
        out.append("• Tarih sinyali yok")
    return out


# ---------------------------------------------------------------- competitors


def _domain(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _key(name: str) -> str:
    """A brand name as a comparable key: folded, letters and digits only ("T-Soft" -> "tsoft", "İkas" -> "ikas")."""
    from .maya_data import name_key
    return name_key(name)


def _label(domain: str) -> str:
    """The registrable domain's own name: "help.shopify.com" -> "shopify", "ideasoft.com.tr" -> "ideasoft"."""
    from .maya_data import domain_label
    return domain_label(domain)


def _own_keys(summary: dict) -> set[str]:
    from .maya_data import brand_keys
    return brand_keys(summary.get("brand_names") or [], summary.get("brand_domains") or [])


# DECISIONS 357: a third-party page lists several brands when its address or title says so (a comparison, a list, the
# best of, alternatives), or when its fetched text names two or more of the brands.
_LISTING = re.compile(r"(?<![a-z])(en iyi|karsilastir\w*|alternatif\w*|vs|versus|best \w+ (?:for|to)|top \d+|\d+ (?:en|best)|liste\w*|"
                      r"hangisi|platformlari|altyapilari|firmalari|sirketleri|comparison|compare|review\w*|inceleme\w*)(?![a-z])")
_NOT_PAGES = re.compile(r"^(images|img|cdn|static|media|assets|i)\.|\.(png|jpe?g|gif|webp|svg|pdf)$")


def competitor_keys(summary: dict) -> dict[str, str]:
    """{key: name} of the competitor brands: the meta's competitors and their aliases, the competitor-mentions names and
    the topic visibility leaders; generic words and the brand's own names left out (DECISIONS 357)."""
    from .maya_data import is_generic
    names: list[str] = []
    for c in summary.get("competitors") or []:
        names += [c.get("name") or ""] + list(c.get("aliases") or [])
    names += [a for a in summary.get("aliases") or [] if isinstance(a, str)]
    for row in ((summary.get("mentions") or {}).get("top") or []):
        names.append(row[0] or "")
    for t in ((summary.get("visibility") or {}).get("topics") or []):
        names.append(t.get("leader") or "")
    from .maya_data import own_name
    own = {_key(n) for n in summary.get("brand_names") or []} | {_label(d) for d in summary.get("brand_domains") or []}
    keys = _own_keys(summary)
    out: dict[str, str] = {}
    for n in names:
        k = _key(n)
        if (len(k) >= 3 and k not in own and not own_name(n, keys) and not is_generic(n) and not k.isdigit()
                and "." not in (n or "").strip(".")):
            out.setdefault(k, n)
    return out


def domain_kind(domain: str, summary: dict, keys: dict[str, str], explicit: set[str], url: str = "",
                text: str | None = None) -> str:
    """brand, competitor (a competitor brand's own site), social, comparison (a third party listing several brands) or
    other (a third party that does not show it does)."""
    from .maya_data import own_domain
    brand = set(summary.get("brand_domains") or [summary.get("domain") or ""]) - {""}
    if any(domain == b or domain.endswith("." + b) for b in brand) or own_domain(domain, _own_keys(summary)):
        return "brand"  # DECISIONS 358: a domain named after the brand (carpex.com.tr) is the brand's own site
    if any(domain == c or domain.endswith("." + c) for c in explicit) or _label(domain) in keys:
        return "competitor"
    if any(domain == s or domain.endswith("." + s) for s in SOCIAL):
        return "social"
    if _NOT_PAGES.search(domain) or _NOT_PAGES.search(urlsplit(url).path.lower()):
        return "other"
    words = _fold(f"{domain} {urlsplit(url).path} {text or ''}".replace("-", " ").replace("/", " ").replace(".", " "))
    if _LISTING.search(words) or (text and sum(1 for k in keys if k in re.sub(r"[^a-z0-9 ]", "", _fold(text)).replace(" ", "")) >= 2):
        return "comparison"
    return "other"


def topic_rows(summary: dict, crawl: "Crawl | None" = None) -> list[dict]:
    ai = summary.get("ai") or {}
    info = ai.get("prompts") or {}
    topics = _topics(summary)
    vis = {t["topic"]: t for t in ((summary.get("visibility") or {}).get("topics") or [])}
    explicit = {c["domain"] for c in summary.get("competitors") or [] if c.get("domain")}
    explicit |= {d for _, _, d in ((summary.get("mentions") or {}).get("top") or []) if d}
    keys = competitor_keys(summary)
    fetched = summary.get("fetched") or {}
    home = (summary.get("origin") or "").rstrip("/")
    by_topic: dict[str, list[str]] = defaultdict(list)
    for pid, t in topics.items():
        if t and info.get(pid, {}).get("active", True):
            by_topic[t].append(pid)
    out = []
    for topic, pids in by_topic.items():
        runs = sum((ai.get("prompt_runs") or {}).get(p, 0) for p in pids)
        brand_runs = sum((ai.get("prompt_brand_runs") or {}).get(p, 0) for p in pids)
        brand_pages: Counter = Counter()  # answers (runs) citing each brand page, each answer once (DECISIONS 357)
        for p in pids:
            brand_pages.update((ai.get("prompt_brand_pages") or {}).get(p) or {})
        urls: Counter = Counter()
        url_prompts: dict[str, set] = defaultdict(set)
        dom_prompts: dict[str, set] = defaultdict(set)
        for p in pids:
            for u, n in ((ai.get("prompt_urls") or {}).get(p) or {}).items():
                urls[u] += n
                url_prompts[u].add(p)
                dom_prompts[_domain(u)].add(p)

        def kind(u):
            m = fetched.get(u) if isinstance(fetched.get(u), dict) else {}
            text = " ".join([m.get("title") or "", m.get("h1") or "", *(m.get("h2") or []), m.get("first") or ""]) if m else None
            return domain_kind(_domain(u), summary, keys, explicit, u, text)
        comp_page = next(((u, n) for u, n in urls.most_common() if kind(u) == "competitor"), None)
        cmp_page = next(((u, n) for u, n in urls.most_common() if kind(u) == "comparison"), None)
        cited = brand_pages.most_common()
        # DECISIONS 357: the brand page compared is the topic's most cited one other than the homepage, unless only the
        # homepage is cited
        own = next((u for u, _ in cited if u.rstrip("/") != home), cited[0][0] if cited else None)
        v = vis.get(topic) or {}
        out.append({"topic": topic, "prompts": pids, "n": len(pids), "runs": runs, "brand_share": brand_runs / runs if runs else None,
                    # a page's share: the answers in the topic that cite it (never above 100%)
                    "brand_pages": [(u, min(1.0, n / runs) if runs else 0) for u, n in cited[:3]],
                    "brand_page": own,
                    "vis": v or None, "gap": v.get("gap"),
                    "domains": [(d, len(ps) / len(pids)) for d, ps in sorted(dom_prompts.items(), key=lambda kv: -len(kv[1]))[:5]],
                    "competitor_page": (comp_page[0], comp_page[1], len(url_prompts[comp_page[0]])) if comp_page else None,
                    "comparison_page": (cmp_page[0], cmp_page[1], len(url_prompts[cmp_page[0]])) if cmp_page else None,
                    "samples": [info[p]["text"] for p in pids[:2] if p in info]})
    # DECISIONS 358: the prompts with only labels that are not topics come after every real topic
    from .maya_data import OFF_TOPIC
    for t in out:
        t["name"] = topic_name(t["topic"], summary, [info[p]["text"] for p in t["prompts"] if p in info])
        if t["topic"] == OFF_TOPIC:
            t["labels"] = sorted({x for p in t["prompts"] for x in (info.get(p, {}).get("labels") or [])
                                  + ([info[p]["topic"]] if info.get(p, {}).get("topic") else [])}, key=str.lower)
    out.sort(key=lambda t: (t["topic"] == OFF_TOPIC, -(t["gap"] if t["gap"] is not None else -999), -t["n"]))
    return out


_RAW_KEY = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)+$")


def topic_name(topic: str, summary: dict, texts: list[str] | None = None) -> str:
    """DECISIONS 359: a topic shown readably. A raw key ("makine-bakim-enerji") becomes words with a capital first letter,
    each word spelt as the topic's own prompts spell it ("bakim" -> "bakım" when they write "bakım"); a Maya label whose
    key is the same is used as it is. Any other name is kept."""
    if not _RAW_KEY.match(topic or ""):
        return topic
    from .maya_data import name_key
    key = name_key(topic)
    labels = {name_key(x): x for p in ((summary.get("ai") or {}).get("prompts") or {}).values()
              for x in [p.get("topic") or ""] if x and not _RAW_KEY.match(x)}
    if key in labels:
        return labels[key]
    every = [p.get("text") or "" for p in ((summary.get("ai") or {}).get("prompts") or {}).values()]

    def spelling(word: str) -> str:
        # the topic's prompts first, then all: a word written as it is, else the start of a longer one ("bakımı");
        # folding keeps the length, so the start has the slug word's letters
        for pool in (texts or [], every):
            seen: Counter = Counter()
            for text in pool:
                for w in re.findall(r"[^\W\d_]+", (text or "").replace("I", "ı").replace("İ", "i").lower()):
                    if _fold(w) == word:
                        seen[(0, w)] += 1
                    elif len(word) >= 4 and _fold(w).startswith(word):
                        seen[(1, w[:len(word)])] += 1
            if seen:
                return min(seen, key=lambda k: (k[0], -seen[k]))[1]
        return word
    words = [spelling(w) for w in re.split(r"[-_]+", topic)]
    first = words[0]
    head = ("İ" + first[1:]) if first.startswith("i") else first[:1].upper() + first[1:]
    return " ".join([head] + words[1:])


def _vis_words(v: dict | None, who: str) -> str:
    if not v:
        return "—"
    if who == "brand":
        return f"{_tr(v['brand_first'])} → {_tr(v['brand_last'])}"
    if not v.get("leader"):
        if v.get("leader_own"):  # DECISIONS 358
            return f"— («{v['leader_own']}» markanın kendisi, rakip sayılmadı)"
        return "—" + (f" («{v['leader_ignored']}» genel bir kelime, rakip sayılmadı)" if v.get("leader_ignored") else "")
    return f"{v['leader']} {_tr(v['leader_first'])} → {_tr(v['leader_last'])}"


def _tr(x) -> str:
    return "—" if x is None else f"{x:.1f}".replace(".", ",")


def insight(t: dict) -> tuple[str, str]:
    v = t.get("vis") or {}
    if t["n"] < 10:
        return ("Panelde bu konuda az prompt var; sonuç yalnız gösterge.", "Önce Maya paneline bu konu için prompt ekleyin.")
    if t.get("gap") is not None and t["gap"] > 15:
        return (f"Büyük açık: konu görünürlüğünde marka %{_tr(v.get('brand_last'))}, lider {v.get('leader')} %{_tr(v.get('leader_last'))}.",
                "Konunun en çok kaynak gösterilen sayfalarındaki soru-cevap, tablo ve sayısal bilgiyi kendi sayfanızda doğrudan verin.")
    if t.get("gap") is not None and t["gap"] < 0:
        return ("Marka bu konuda lider rakipten önde.", "Koruyun; içerik güncel kalsın.")
    if t.get("brand_share") is not None and t["brand_share"] < 0.2:
        return ("Markanın sayfaları bu konuda az kaynak gösteriliyor.", "Konunun sorularını cevaplayan bir sayfa ya da bölüm ekleyin.")
    return ("Açık orta düzeyde.", "Kaynak gösterilen karşılaştırma sayfalarıyla kendi sayfanızı karşılaştırın.")


def topic_sheet(summary: dict, rows: list[dict]) -> dict:
    header = ["Öncelik", "Konu", "Panel prompt (n)", "Yalnız gösterge (n<10)", "Marka citation payı (koşu)",
              "Markanın kaynak gösterilen sayfaları (konudaki cevapların payı)", "Konu görünürlüğü marka (ilk → son hafta)",
              "Lider rakip (ilk → son hafta)", "Fark (puan, son hafta)", "En çok kaynak gösterilen alan adları (prompt payı)",
              "En çok kaynak gösterilen rakip marka sayfası", "En çok kaynak gösterilen karşılaştırma sayfası",
              "Üçüncü taraf listelerde marka sırası", "İçgörü", "Önerilen aksiyon", "Örnek prompt'lar"]
    body = []
    for i, t in enumerate(rows, 1):
        why, act = insight(t)
        topic = (f"{t['topic']} ({', '.join(t['labels'][:8])})" if t.get("labels") else t.get("name") or t["topic"])
        body.append([i, topic, t["n"], "Evet" if t["n"] < 10 else "", _pct(t["brand_share"]),
                     "; ".join(f"{_short(u)} ({round(100 * s)}%)" for u, s in t["brand_pages"]),
                     _vis_words(t["vis"], "brand"), _vis_words(t["vis"], "leader"), t["gap"] if t["gap"] is not None else "",
                     "; ".join(f"{d} ({round(100 * s)}%)" for d, s in t["domains"]),
                     f"{_short(t['competitor_page'][0])} ({t['competitor_page'][1]} koşu, {t['competitor_page'][2]} prompt)" if t["competitor_page"] else "—",
                     f"{_short(t['comparison_page'][0])} ({t['comparison_page'][1]} koşu, {t['comparison_page'][2]} prompt)" if t["comparison_page"] else "—",
                     "—", why, act, " | ".join(t["samples"])])
    return {"name": SHEETS["topics"], "header": header, "rows": body,
            "widths": [8, 30, 10, 10, 12, 50, 18, 26, 10, 60, 50, 50, 18, 60, 60, 80]}


def structure_targets(topics: list[dict], summary: dict) -> list[tuple[str, str, str | None]]:
    """(topic, side, url) for each topic: the brand's most cited page, the most cited competitor-brand page and
    comparison page (at most MAX_EXTERNAL_PER_TOPIC external pages per topic)."""
    from .maya_data import OFF_TOPIC
    out = []
    for t in topics:
        if t["topic"] == OFF_TOPIC:  # not a topic: no page of it is compared (DECISIONS 358)
            continue
        out.append((t["topic"], "Marka", t.get("brand_page")))
        ext = [("Rakip marka", t["competitor_page"][0] if t["competitor_page"] else None),
               ("Karşılaştırma sitesi", t["comparison_page"][0] if t["comparison_page"] else None)]
        for side, url in ext[:MAX_EXTERNAL_PER_TOPIC]:
            out.append((t["topic"], side, url))
    return out


def structure_sheet(topics: list[dict], summary: dict, crawl: Crawl) -> dict:
    header = ["Konu", "Taraf", "Sayfa", "Ana metin (kelime)", "H2", "Soru biçimli H2", "Tablo (≥3 satır)", "FAQ şema soru",
              "Sayısal değer", "Tarih sinyali", "Şema tipleri", "İlk cümle", "Fark [HİPOTEZ]"]
    body = []
    for topic in topics:
        group = [(side, url) for t, side, url in structure_targets([topic], summary)]
        if not group:
            continue
        shown = topic.get("name") or topic["topic"]
        measured = {side: (url, crawl.measure(url) if url else None) for side, url in group}
        mine = measured.get("Marka", (None, None))[1]
        for side, (url, m) in measured.items():
            if not url:
                body.append([shown, side, "—", "", "", "", "", "", "", "", "", "", ""])
                continue
            if m is None or m.get("error"):
                body.append([shown, side, _link(url), "alınamadı" if side != "Marka" else "okunmadı"] + [""] * 9)
                continue
            body.append([shown, side, _link(url), _words(m), len(m["h2"]), m["question_h2"], m["tables"],
                         _blank(m["faq_questions"]), _blank(m["numbers"]), "Evet" if m["dated"] else "Hayır", ", ".join(m["types"]),
                         m["first"] or "", difference(mine, m) if side != "Marka" else ""])
    return {"name": SHEETS["structure"], "header": header, "rows": body,
            "widths": [26, 18, 60, 18, 6, 10, 10, 10, 10, 10, 40, 60, 60]}


def difference(mine: dict | None, other: dict) -> str:
    if not mine:
        return ""
    has = []
    if other.get("tables") and not mine.get("tables"):
        has.append("HTML tablo")
    if (other.get("faq_questions") or other.get("question_h2")) and not (mine.get("faq_questions") or mine.get("question_h2")):
        has.append("soru-cevap")
    if other.get("dated") and not mine.get("dated"):
        has.append("tarih sinyali")
    if (other.get("numbers") or 0) > 2 * max(1, mine.get("numbers") or 0):
        has.append("daha çok sayısal değer")
    return (f"Rakipte var, markada yok: {', '.join(has)} [HİPOTEZ: citation nedeni olarak kanıtlanmadı]" if has else "")


# ---------------------------------------------------------------- the whole


def build(summary: dict | None, report: dict, evidence_dir: Path | None = None, records: dict[str, dict] | None = None,
          profile: str | None = None) -> dict[str, Any]:
    """{"sheets": [...], "howto": [[text, link]], "coverage": [text], "method": [[part, value]]}. `records`, `profile`:
    the selection's page records and business type (DECISIONS 357), so every sheet names a page's type alike."""
    if not summary:
        return {"sheets": [], "howto": [], "coverage": ["Maya verisi eklenmedi: Search Console, AI citation ve rakip sayfaları yok."],
                "method": []}
    crawl = Crawl(report, evidence_dir, summary.get("fetched"), records, profile)
    missing = summary.get("missing") or {}
    sheets, howto, coverage, method = [], [], [], []
    datasets = ", ".join(f"{d['dataset']} ({(d.get('period') or ['', ''])[0]} – {(d.get('period') or ['', ''])[1]})"
                         if d.get("period") else d["dataset"] for d in summary.get("datasets") or [])
    coverage.append(f"Maya verisi: {summary['domain']}; kullanılan dosyalar: {datasets}")
    if summary.get("other_files"):
        coverage.append(f"Maya verisi: tanınmayan dosyalar kullanılmadı: {', '.join(summary['other_files'][:10])}")

    def skipped(sheet_key: str, label: str) -> bool:
        if missing.get(sheet_key):
            coverage.append(f"{label} sayfası oluşturulmadı: eksik veri seti {', '.join(missing[sheet_key])}")
            return True
        return False
    if not skipped("overview", SHEETS["overview"]):
        sheets.append({"name": SHEETS["overview"], "header": ["Genel durum"], "rows": overview_rows(summary),
                       "widths": [36, 14, 14, 14, 14, 18, 18], "filter": False})
        howto.append(f"«{SHEETS['overview']}»: aylık Search Console, AI cevaplarında kaynak payı, sağlayıcı ve konu bazında marka payı.")
    rows: list[dict] = []
    if not skipped("organic_ai", "Organik×AI"):
        s1, s2, rows, th = segment_sheets(summary, crawl)
        sheets += [s1, s2]
        howto.append(f"«{SHEETS['summary']}»: sayfalar Search Console ve AI kaynak gösterimine göre segmentlere ayrıldı; "
                     "«Satırlara git» segmentin satırlarını açar.")
        howto.append(f"«{SHEETS['segments']}»: her sayfa bir satır; kopya adresler asıl sayfaya katıldı.")
        gsc = summary.get("gsc") or {}
        if not gsc.get("pages"):
            coverage.append("Organik×AI: sayfa bazında Search Console verisi yok (gsc-search-performance ya da gsc-page-scores); "
                            "tüm sayfalar «GSC'de ölçülmedi», bu «zayıf» anlamına gelmez")
        else:
            coverage.append(f"Organik veri: {gsc.get('page_source')} ({'28 günlük anlık görüntü, toplanmadı' if gsc.get('page_kind') == 'snapshot' else 'günlük satırlar toplandı'}"
                            + (f", {gsc['page_period'][0]} – {gsc['page_period'][1]}" if gsc.get("page_period") else ", dönemi dosyada belirtilmemiş") + ")")
        if (gsc.get("weekly_sample") or {}).get("period"):
            w = gsc["weekly_sample"]
            coverage.append(f"«GSC haftalık tık» sütunu ayrı kaynak: gsc-top-pages (haftalık ilk sayfalar, {w['weeks']} hafta, "
                            f"{w['period'][0]} – {w['period'][1]}); karşılaştırma için gösterilir, segmentlere katılmaz")
        ai = summary.get("ai") or {}
        if ai.get("period"):
            coverage.append(f"AI verisi: citation-mentions {ai['period'][0]} – {ai['period'][1]}, {len(ai.get('prompts') or {})} prompt, "
                            f"{len(ai.get('providers') or {})} sağlayıcı")
        method += [["Önem puanı (0–100)", "40 × gösterim yüzdelik sırası + 40 × AI prompt yüzdelik sırası + sayfa türü ağırlığı "
                                          "(ana sayfa/ürün +20, ücret +15, destek/blog +10, kampanya +5, hukuki −20, form −30)"],
                   ["Segment eşikleri", f"sitenin kendi dağılımından: organikte güçlü tık ≥ {round(th['org_strong'])} (üst çeyrek), "
                                        f"zayıf < {round(th['org_weak'])} (medyan); AI'da güçlü ≥ {round(th['ai_strong'])} prompt, "
                                        f"az < {round(th['ai_few'])}; gösterim yüksek ≥ {round(th['impr_high'])}"],
                   ["«GSC'de yok»", "organik veri ölçülmedi; «zayıf» değildir"],
                   ["Kopya adresler", "/anasayfa, /default.aspx gibi adresler ve kanoniği başka sayfa olanlar asıl sayfaya katıldı"],
                   ["Korelasyon", CORRELATION]]
        if not skipped("page_detail", SHEETS["detail"]):
            sheets.append(detail_sheet(summary, crawl, rows))
            howto.append(f"«{SHEETS['detail']}»: önem puanına göre ilk {MAX_DETAIL} sayfa; sayfa yapısı ve aynı prompt'larda kaynak "
                         "gösterilen rakip sayfalar.")
            not_read = sum(1 for r in rows[:MAX_DETAIL] if crawl.measure(r["url"]) is None)
            got = fetched_counts(summary)
            if got["detail"]:
                coverage.append(f"Sayfa detay: denetimde okunmayan {got['detail']} sayfa Maya verisi eklenirken ayrıca indirildi")
            if not_read:
                coverage.append(f"Sayfa detay: {not_read} sayfa bu denetimde okunmadı ve ayrıca indirilmedi («okunmadı»)"
                                + ("" if (summary.get("fetch") or {}).get("wanted") else "; Maya verisi kartında «sayfaları da indir» "
                                   "seçilip yeniden okunursa indirilir"))
    if not skipped("competitors", "Rakip"):
        topics = topic_rows(summary, crawl)
        if topics:
            sheets.append(topic_sheet(summary, topics))
            sheets.append(structure_sheet(topics, summary, crawl))
            howto.append(f"«{SHEETS['topics']}»: konu bazında marka ve lider rakip, en büyük açık en üstte; n < 10 yalnız gösterge.")
            howto.append(f"«{SHEETS['structure']}»: marka sayfası, rakip ve karşılaştırma sayfası yan yana; farklar [HİPOTEZ].")
            got = fetched_counts(summary)
            asked = (summary.get("fetch") or {}).get("wanted")
            coverage.append(f"Rakip sayfaları: konu başına en çok {MAX_EXTERNAL_PER_TOPIC} dış sayfa; indirilen {got['competitor']}"
                            + (f", alınamayan {got['failed']}" if got["failed"] else "")
                            + ("" if asked or got["pages"] else " («sayfaları da indir» seçilmedi)")
                            + "; denetlenen sitenin sayfa sınırına sayılmadı; alınamayan sayfa «alınamadı»")
            method.append(["Rakip konuları", "prompt'lar Maya etiketiyle (meta.json) ya da konu adının kelimeleriyle tek konuya atandı; "
                                             "«maid», «handyman», «urban» gibi tek başına genel kelimeler rakip sayılmadı; "
                                             "«intent:», «register:», «brand:» gibi konu olmayan etiketler «Konu dışı etiketler» "
                                             "satırında, gerçek konulardan sonra"])
            own = summary.get("own") or {}
            if own.get("names") or own.get("products"):
                said = ", ".join("«" + n + "»" for n in (own.get("names") or [])[:8])
                more = (f"{len(own['products'])} ürün adı (ör. «{own['products'][0]}»)" if own.get("products") else "")
                coverage.append("Markanın kendisi: Maya'nın rakip verisindeki " + " ve rakip anma verisindeki ".join(x for x in (said, more) if x)
                                + " markanın kendi adı ya da ürünü; hiçbir sayfada rakip sayılmadı")
            if own.get("domains"):
                coverage.append(f"Markanın kendi siteleri: {', '.join(own['domains'][:8])} markanın adını taşıdığı için markanın "
                                "sitesi sayıldı (rakip değil); kaynak gösterilen sayfaları marka payına katıldı")
        else:
            coverage.append("Rakip sayfaları oluşturulmadı: prompt'lar hiçbir konuya atanamadı")
    method.append(["Maya verisi", "Search Console 28 günlük anlık satırları toplanmaz (son görüntü), günlük satırlar toplanır; "
                                  "her sayı veri seti ve dönemiyle verilir"])
    return {"sheets": sheets, "howto": howto, "coverage": coverage, "method": method}


# ---------------------------------------------------------------- pages to fetch


def enrich(summary: dict, report: dict, fetch: Callable[[str], str | None], evidence_dir: Path | None = None,
           limit: int = 60) -> dict:
    """Fetch, once, the pages the sheets would show and the crawl did not read: the top pages of "Sayfa detay" and up
    to MAX_EXTERNAL_PER_TOPIC external pages per topic. `fetch(url)` returns the HTML or None (the caller's polite
    fetcher; never counted toward the audited site's page limit). Stored in `summary["fetched"]`."""
    crawl = Crawl(report, evidence_dir, {})
    wanted: dict[str, str] = {}  # url -> what it is for: "detail" (Sayfa detay) or "competitor" (Rakip sayfaları)
    if not (summary.get("missing") or {}).get("page_detail"):
        rows, _ = pages(summary, crawl)
        # only pages the crawl never asked for: an address it answered (a redirect, a 404) is the site's own answer
        for r in [r for r in rows if r["segment"] and r["segment"] != "0"][:MAX_DETAIL]:
            if crawl.measure(r["url"]) is None and r["url"] not in crawl.pages:
                wanted.setdefault(r["url"], "detail")
    if not (summary.get("missing") or {}).get("competitors"):
        for _, side, url in structure_targets(topic_rows(summary), summary):
            if url and crawl.measure(url) is None and url not in crawl.pages:
                wanted.setdefault(url, "detail" if side == "Marka" else "competitor")
    fetched = dict(summary.get("fetched") or {})
    for url, purpose in list(wanted.items())[:limit]:
        if url in fetched and not fetched[url].get("error"):
            continue
        try:
            html = fetch(url)
        except Exception as exc:  # noqa: BLE001  a page that cannot be fetched is "alınamadı"
            fetched[url] = {"error": type(exc).__name__, "for": purpose}
            continue
        fetched[url] = {**(measure_html(html) if html else {"error": "no page"}), "for": purpose}
    summary["fetched"] = fetched
    return summary


def fetched_counts(summary: dict | None) -> dict[str, int]:
    """DECISIONS 358: what the "also download pages" choice brought: pages per purpose and the ones that failed."""
    rows = [v for v in ((summary or {}).get("fetched") or {}).values() if isinstance(v, dict)]
    ok = [v for v in rows if not v.get("error")]
    return {"pages": len(ok), "detail": sum(1 for v in ok if v.get("for") == "detail"),
            "competitor": sum(1 for v in ok if v.get("for") != "detail"), "failed": len(rows) - len(ok)}


__all__ = ["build", "enrich", "fetched_counts", "pages", "topic_rows", "is_generic", "measure_html"]
