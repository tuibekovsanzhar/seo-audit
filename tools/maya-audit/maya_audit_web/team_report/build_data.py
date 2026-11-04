"""Maya Audit report.json (şema 1.x) -> data.json (4 sayfalık profesyonel rapor taslağı).

Sayıların hepsi report.json'dan deterministik olarak çıkar. Model yalnız `⟪YAZ: …⟫` işaretli metin
alanlarını doldurur; hangi alanlar olduğu `_slots` listesinde yazılıdır. Denetleyici (validate_data.py)
işaret kalmışsa, metinde rapora dayanmayan bir sayı varsa ya da dil karışmışsa basmayı durdurur.

Kullanım:
  python build_data.py report.json --lang tr|en -o data.json [--rev r3] [--audit-id ID] [--maya-src KLASÖR]

--lang zorunludur, varsayılanı yoktur (dil her raporda kullanıcıya sorulur).
--maya-src: Maya Audit kaynak klasörü (içinde maya_audit_web/ olan). Verilirse ya da paket kuruluysa motorun
kendi Türkçe çevirileri (wording.py) kullanılır; bulunamazsa o başlıklar modele bırakılır.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

if __package__ in (None, ""):  # run as a script: the engine is the folder two levels up (tools/maya-audit)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from maya_audit_web.team_report import texts as T  # noqa: E402

HERE = Path(__file__).resolve().parent
REFS = HERE / "refs"
SEVERITIES = ("S1", "S2", "S3", "S4")
MEDIUM_UP = ("S1", "S2", "S3")
MARK = "⟪YAZ: {}⟫"
# DECISIONS 284 (1): findings with one cause are one card. The empty-response rules (one cause when on the same sections).
EMPTY_RULES = frozenset({"idx1.empty", "judgment.empty.repeated", "judgment.empty.single"})
# DECISIONS 284 (5): why a sitemap address needs review (an error page: Location /404, not-found or aspxerrorpath), from the engine's per-address decisions. Order breaks ties.
SITEMAP_REASONS = ("redirect_404", "redirect", "empty_repeated", "empty_single", "not_found", "server_error", "noindex", "other")
ERROR_PAGE = re.compile(r"/(?:404|not[-_]?found)(?:[/?.#]|$)|aspxerrorpath", re.I)
# Evidence-sample rows that fit the box above its note; a fourth row printed over the note (Enpara render).
EV_ROWS = 3
CONFIRM_SHOWN = 10  # "Teyit edin" lines the last page has room for; the rest are counted and in the appendix
MAX_CARDS = 15  # DECISIONS 300: a client report has at most 15 cards (release gate RG-16)


def platform_steps(rule, platform, lang):
    """The engine catalogue's steps for this rule on this platform (DECISIONS 300 (7)), or None."""
    try:
        from maya_audit.client_selection import platform_steps as steps  # type: ignore
        return steps(rule, platform, lang)
    except Exception:
        return None
# Maya Audit STR-3 «expected type» sayfa türü → müşteriye önerilecek tip
KIND_SCHEMA = {"product": "Product", "article": "Article", "pricing": "Product + Offer", "faq": "FAQPage"}
LAB_LABELS = {
    "Largest Contentful Paint": {"tr": "En büyük içerik boyaması (LCP)", "en": "Largest Contentful Paint"},
    "Total Blocking Time": {"tr": "Toplam engelleme süresi (TBT)", "en": "Total Blocking Time"},
    "Cumulative Layout Shift": {"tr": "Kümülatif düzen kayması (CLS)", "en": "Cumulative Layout Shift"},
}
COUNTRIES_TR = {"Turkey": "Türkiye", "United States": "ABD", "United Kingdom": "Birleşik Krallık", "Germany": "Almanya",
                "France": "Fransa", "Netherlands": "Hollanda", "Spain": "İspanya", "Italy": "İtalya",
                "United Arab Emirates": "BAE", "Saudi Arabia": "Suudi Arabistan", "Azerbaijan": "Azerbaycan"}
FIXED = {
    "commercial": {
        "tr": "Sıralama ve arama hacmi görünürlüğü gösterir; satış niyetini ya da dönüşüm değerini göstermez. İçeriğe öncelik vermeden önce hedef kitleye uygunluğunu değerlendirmelisiniz.",
        "en": "Search rank and volume establish visibility, not sales intent or conversion value. Assess audience fit before prioritising content.",
    },
    "limits": {
        "tr": "Mobil skor, ana sayfadaki tek bir laboratuvar testidir. Genel bir SEO puanı ya da gerçek kullanıcı ölçümü değildir.",
        "en": "The mobile score covers one homepage lab test. It is not an overall SEO score or a real-user measurement.",
    },
    "limits_action": {
        "tr": "Sonucu benzer bir yerel testle doğrulamalı ve istek şelalesini incelemelisiniz.",
        "en": "Confirm performance with a comparable local test and review the request waterfall.",
    },
    "perf_action": {
        "tr": "Mobil laboratuvar sonucunu doğrulayın; {metrics} metriklerini inceleyin",
        "en": "Validate the mobile lab result; investigate {metrics}",
    },
}


# ---------------------------------------------------------------- yardımcılar
def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def num(text):
    m = re.search(r"\d[\d,.]*", str(text or ""))
    return int(re.sub(r"[,.]", "", m.group(0))) if m else None


def fmt_int(n, lang):
    if not isinstance(n, (int, float)):
        return str(n)
    s = f"{int(n):,}"
    return s.replace(",", ".") if lang == "tr" else s


def parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def date_long(s, L):
    d = parse_dt(s)
    return f"{d.day} {L['months'][d.month - 1]} {d.year}" if d else "—"


def date_short(s, L):
    d = parse_dt(s)
    return f"{d.day} {L['months_short'][d.month - 1]} {d.year}" if d else "—"


def path_of(url):
    if not url:
        return ""
    p = urlsplit(url)
    return (p.path or "/") + (("?" + p.query) if p.query else "")


def load_final(maya_src=None):
    """Maya Audit's shared final result (maya_audit.final, DECISIONS 280): as installed, at --maya-src, or in the
    repository holding this skill. None when the engine cannot be found; the skill then builds nothing."""
    for where in [None, maya_src and str(Path(maya_src).resolve()), str(HERE.parents[1])]:
        if where and where not in sys.path and (Path(where) / "maya_audit" / "final.py").exists():
            sys.path.insert(0, where)
        try:
            from maya_audit import final  # type: ignore
            return final
        except ImportError:
            continue
    return None


# Checks whose scope is a list of addresses (URL), not pages; a rule of theirs whose scope is the pages that carry the
# problem says "sayfa" (DECISIONS 305: the links to an alias are counted on the pages that hold them).
URL_SCOPED = ("IDX-1", "IDX-6", "IDX-3", "IDX-5")
PAGE_SCOPED_RULES = frozenset({"idx6.alias_links"})

def unread_part_names():
    """The engine's names for parts that restate the unread addresses; the engine is required (load_final)."""
    if load_final() is None:
        raise RuntimeError("Maya Audit motoru (maya_audit) bulunamadı")
    from maya_audit.coverage import UNREAD_RESTATEMENTS  # type: ignore
    return UNREAD_RESTATEMENTS


def link_rows(cards):
    """A broken link's "what to edit" rows (maya_audit.final.broken_link_cards): page to edit, link text, the address
    it links to, where it ends and that address's status. The new address is never known, so never guessed."""
    keys = ("kind", "source_url", "link_text", "links_to", "target_url", "target_status", "replacement_url")
    return [{k: c.get(k) for k in keys} for c in cards or []]


class Wording:
    """Motorun kendi çeviri katmanı (maya_audit_web.wording), varsa."""

    def __init__(self, lang, maya_src):
        self.lang, self.mod = lang, None
        if maya_src:
            sys.path.insert(0, str(Path(maya_src).resolve()))
        try:
            from maya_audit_web import wording  # type: ignore
            self.mod = wording
        except Exception:
            self.mod = None

    def title(self, check_id, text):
        """(metin, motor_çevirisi_mi). EN'de motorun İngilizce görüntü kalıbı; TR'de çeviri ya da None."""
        if self.mod is not None:
            try:
                out, ok = self.mod.title(check_id, text, self.lang)
                if ok:
                    return out, True
            except Exception:
                pass
        if self.lang == "en":
            return english(text), False
        return None, False

    def expected(self, text):
        if self.mod is not None and text:
            try:
                out, ok = self.mod.expected(text, self.lang)
                if ok:
                    return out, True
            except Exception:
                pass
        return (text, False) if self.lang == "en" else (None, False)

    def rule(self, check_id, title):
        """Kural kimliği (Maya Audit 1.18 `rule_id`); eski raporda motorun kural tablosundan (DECISIONS 269)."""
        try:
            from maya_audit.rules import rule_id  # type: ignore
            return rule_id(check_id, title)
        except Exception:
            return None

    def facts(self, rule, evidence):
        """Motorun yapılandırılmış kanıtı (DECISIONS 271); eski raporda motorun çıkarıcısıyla üretilir."""
        if (evidence or {}).get("facts"):
            return evidence["facts"]
        try:
            from maya_audit.facts import EXTRACTORS, MAX_FACTS  # type: ignore
            extract = EXTRACTORS.get(rule or "")
            return [r for r in extract(evidence or {}) if r][:MAX_FACTS] if extract else []
        except Exception:
            return []

    def _entry(self, rule):
        if not rule:
            return {}
        try:
            import maya_audit  # type: ignore
            actions = json.loads((Path(maya_audit.__file__).parent / "rule_actions.json").read_text(encoding="utf-8"))
            return (actions.get("actions") or {}).get(rule) or {}
        except Exception:
            return {}

    def owner(self, check_id, title):
        """(sorumlu, efor) from the engine's own catalogue (maya_audit.recommendation_catalog), or None without the
        engine. The static `sahip_efor.json` is only the fallback: it was copied once and went stale (an early-closed
        <head> and a hidden <h1> came out as content work)."""
        if load_final() is None:
            return None
        try:
            from maya_audit.recommendation_catalog import note  # type: ignore
            found = note(check_id or "", title or "")
            return found["owner"], found["effort"]
        except Exception:
            return None

    def action(self, rule):
        """Kural kataloğundaki iş başlığı (maya_audit/rule_actions.json, DECISIONS 270), ya da None."""
        return self._entry(rule).get(self.lang)

    def steps(self, rule, findings=()):
        """Kural kataloğundaki adımlar, kart biçiminde (satır satır), ya da None."""
        return self.step_rules(rule, findings)[0]

    def step_rules(self, rule, findings=()):
        """(adımlar ya da None, [{"text", "when", "shown"}]). Koşullu bir adım (`step_when`, DECISIONS 278) yalnız
        bulgunun kanıtı koşulu sağlıyorsa karta girer; koşulu yayın kapısının kendi işlevi değerlendirir."""
        entry = self._entry(rule)
        lines = (entry.get("steps") or {}).get(self.lang)
        if not lines:
            return None, []
        conditions = entry.get("step_when") or []
        rules, kept = [], []
        for n, line in enumerate(lines):
            when = conditions[n] if n < len(conditions) else None
            if when:
                try:
                    from maya_audit.release_gate import condition_met  # type: ignore
                    shown = condition_met(when, list(findings))
                except Exception:
                    shown = False  # no gate, no conditional step (and no PDF: render.py refuses)
                rules.append({"text": line, "when": when, "shown": shown})
                if not shown:
                    continue
            kept.append(line)
        return ("\n".join(kept) if kept else None), rules

    def fix(self, text):
        if self.mod is not None and text:
            try:
                out, ok = self.mod.fix(text, self.lang)
                if ok:
                    return out, True
            except Exception:
                pass
        return (text, False) if self.lang == "en" else (None, False)


# Not kartlarının sabit başlık ve doğrulama cümleleri (DECISIONS 270); adımlar siteye özgü kalır (model yazar).
NOTE_TEXT = {
    "schema": {"tr": ("Sayfaların gösterdiği bilgiyi yapısal veriyle işaretleyin",
                      "Schema Markup Validator eklenen tipleri hatasız listelemeli."),
               "en": ("Mark up the structured data these pages describe",
                      "Schema Markup Validator lists the added types without errors.")},
    "hygiene": {"tr": ("Küçük bağlantı ve etiket tutarsızlıklarını temizleyin",
                       "Bir sonraki Maya denetiminde bu maddeler listelenmemeli."),
                "en": ("Clean up small link and tag inconsistencies", "The next Maya audit no longer lists these.")},
    "perf": {"tr": ("Sayfa yüklemesini ve etiketleri toparlayın", "Bir sonraki Maya denetiminde bu maddeler listelenmemeli."),
             "en": ("Speed up and tidy how the pages load", "The next Maya audit no longer lists these.")},
}

# Konu adlı Not kartlarının başlığı ve doğrulaması yalnız raporda bulunan konulardan kurulur (DECISIONS 278): bir
# sitenin bulgularından yazılmış sabit başlık, o konuların olmadığı sitede kanıtsız sorun söylüyordu.
# konu: {dil: (başlıktaki ad, doğrulama cümlesi)}
NOTE_TOPICS = {
    "content": {
        "menu": {"tr": ("menü dilini", "menü sayfanın dilinde görünmeli"),
                 "en": ("menu language", "the menu is in the page's language")},
        "questions": {"tr": ("soru başlıklarını", "sorular başlık olarak görünmeli"),
                      "en": ("question headings", "questions show as headings")},
        "address": {"tr": ("adres yazımını", "adres sözcükleri sayfanın adıyla uyuşmalı"),
                    "en": ("address spelling", "address words match the page's name")},
    },
    "share": {
        "share_image": {"tr": ("paylaşım görselini", "paylaşım önizlemesinde büyük görsel çıkmalı"),
                        "en": ("share image", "share previews show a large image")},
        "video": {"tr": ("video işaretlemesini", "VideoObject gerçek videoyu anlatmalı"),
                  "en": ("video markup", "VideoObject describes the real video")},
        "image_format": {"tr": ("görsel biçimini", "görsel dosyası adının söylediği biçimde sunulmalı"),
                         "en": ("image formats", "images are served in the format their name says")},
    },
}


def topic_text(kind, topics, lang):
    """(başlık, doğrulama) yalnız verilen konulardan: «Menü dilini ve soru başlıklarını düzeltin»."""
    names = [NOTE_TOPICS[kind][t][lang][0] for t in topics]
    checks = [NOTE_TOPICS[kind][t][lang][1] for t in topics]
    if lang == "tr":
        joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " ve " + names[-1]
        title = f"{joined[0].upper()}{joined[1:]} düzeltin"
    else:
        joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        title = f"Fix {joined}"
    verify = "; ".join(checks)
    return title, verify[0].upper() + verify[1:] + "."


# Kart adımları kutusuna güvenle sığan biçim (DECISIONS 270): en çok 4 satır, satır başına en çok 75 karakter.
STEP_LINES, STEP_CHARS = 4, 75


def steps_from(text):
    """Motorun düzeltme cümlesini kart adımlarına böler; kutuya sığmıyorsa None (alan modele kalır)."""
    parts = [s.strip().rstrip(".") for s in re.split(r"(?<=[.;])\s+|;\s*", text or "") if s.strip()]
    lines = [p[0].upper() + p[1:] for p in parts if p]
    if not lines or len(lines) > STEP_LINES or any(len(line) > STEP_CHARS for line in lines):
        return None
    return "\n".join(lines)


_ADDRESS = re.compile(r"https?://[^\s\"'<>]+|(?<![\w:/.<>])/[A-Za-z0-9][\w\-.%]*(?:/[\w\-.%#]+)*/?")


def known_paths(*values) -> list[str]:
    """Every site path a finding's own record names (title, scope, evidence, fix): what its card may quote (DECISIONS 271)."""
    found = set()
    for m in _ADDRESS.findall(json.dumps(values, ensure_ascii=False)):
        path = urlsplit(m).path if m.startswith("http") else m.split("#")[0]
        for part in [path] + [p for p in m.split("#")[1:]]:
            if part.startswith("/"):
                found.add(part.rstrip("/") or "/")
    return sorted(found)[:600]


def fact_line(facts, L):
    """The card's evidence line from engine facts: address · element · value (limit), first fact, "+N" for the rest."""
    if not facts:
        return None
    f = facts[0]
    url = f.get("url")
    where = (path_of(url) if path_of(url) not in ("", "/") else "/") if url else None
    element = f.get("element")
    if isinstance(element, str) and element.startswith(("http://", "https://")):
        element = path_of(element) or "/"
    value = f.get("observed")
    if value and f.get("expected"):
        value = f"{value} ({L['fact_limit']} {f['expected']})"
    parts = [str(x) for x in (where, element, value) if x not in (None, "")]
    line = " · ".join(parts)
    if len(facts) > 1:
        line += f" · +{len(facts) - 1}"
    return line[:110] if line else None


def english(text):
    """'1 page(s) are' -> '1 page is'; '9 page(s)' -> '9 pages'."""
    def one(m):
        n, word = int(m.group(1).replace(",", "")), m.group(2)
        return f"{m.group(1)} {word}" if n == 1 else f"{m.group(1)} {word}s"
    out = re.sub(r"(\d[\d,]*) (\w+?)\(s\)", one, text or "")
    out = re.sub(r"\b1 (\w+) are\b", r"1 \1 is", out)
    return out.replace("(s)", "s")


# ---------------------------------------------------------------- çekirdek
class Builder:
    def __init__(self, report, lang, labels, catalog, wording, rev, audit_id, reanalysis=False, affected=None, cards=None,
                 selection=None):
        self.r, self.lang, self.L, self.cat, self.w = report, lang, labels, catalog, wording
        # DECISIONS 300: the cards, their order and what goes to "Teyit edin" or the appendix come from Maya Audit's one
        # client selection (maya_audit.client_selection), the same one the web app's concise PDF uses.
        self.sel = selection
        self.held = {fid for g in (selection or {}).get("groups") or [] if g.get("placement") in ("confirm", "rejected")
                     for fid in g["finding_ids"]}
        # A report that is itself an offline reanalysis says so in its own record (DECISIONS 307): the web app and the
        # skill then say "no new crawl" without a flag.
        self.rev, self.audit_id = rev, audit_id
        self.reanalysis = bool(reanalysis or (report.get("generation") or {}).get("analysis"))
        self.slots, self.facts = [], set()
        self.affected = affected or {}
        # broken-link rows from the final result (maya_audit.final.broken_link_cards), by finding id
        self.cards = cards or {}
        self.findings = {}
        for chk in report.get("checks") or []:
            for f in chk.get("findings") or []:
                self.findings[f["id"]] = f
        order = report.get("findings_in_priority_order") or list(self.findings)
        self.ordered = [self.findings[i] for i in order if i in self.findings]
        self.problems = [f for f in self.ordered if f.get("severity") in SEVERITIES]
        self.dfs = {c.get("check_id"): c for c in (report.get("dataforseo") or {}).get("checks") or []}

    def _w(self, name):
        """A wording method that older or stand-in wording objects may lack (DECISIONS 270): then nothing is prefilled."""
        return getattr(self.w, name, None) or (lambda *args: [] if name == "facts" else None)

    # -- model alanları
    def slot(self, path, hint, src=None, maxlen=None, prefill=None, lines=None, fallback=None):
        """A text field: the engine's or the catalogue's own words (`prefill`) when they fit the box, else the text
        library's (`fallback`, DECISIONS 307). The skill may still polish either; `⟪YAZ⟫` is left only when neither
        exists (`finish` then gives the library's generic words, so no report has an empty field)."""
        self.slots.append({"path": path, "hint": hint, "src": src, "max": maxlen, **({"lines": lines} if lines else {})})
        for text in (prefill, fallback):
            if text and self.fits(text, maxlen, lines):
                return text
        return prefill or fallback or MARK.format(hint)

    @staticmethod
    def fits(text, maxlen, lines):
        if maxlen and len(text) > maxlen:
            return False
        if lines:
            rows = [r for r in text.split("\n") if r.strip()]
            return 2 <= len(rows) <= lines and all(len(r) <= T.STEP_CHARS for r in rows)
        return True

    def confidence_of(self, f):
        """The selection's confidence class of this finding's card (measured / estimated / inferred / unverified)."""
        for g in (self.sel or {}).get("groups") or []:
            if f.get("id") in g.get("finding_ids", []):
                return g.get("confidence")
        return None

    def lib(self, f, merged=True):
        """The text library's entry for this finding's card (its merge group's or its rule's), DECISIONS 307."""
        if f is None:
            return T.library(self.lang)["generic"]
        rule = f.get("rule_id") or self._w("rule")(f.get("check_id"), f.get("title"))
        return T.for_finding({**f, "rule_id": rule}, self.lang, merged=merged)

    def finish(self, data):
        """Every slot still marked gets the library's generic words for its kind of field: no empty text field."""
        generic = T.library(self.lang)["generic"]
        kinds = (("steps", "\n".join(generic["steps"])), ("verify", generic["verify"]), ("title", generic["title"]),
                 ("label", generic["summary"]), ("lead", generic["title"] + "."), ("headline", generic["explanation"]),
                 ("", generic["explanation"]))
        for s in self.slots:
            parts = re.findall(r"[^.\[\]]+", s["path"])
            o = data
            for x in parts[:-1]:
                o = o[int(x)] if x.isdigit() else o.get(x) if isinstance(o, dict) else None
                if o is None:
                    break
            if o is None:
                continue
            key = int(parts[-1]) if parts[-1].isdigit() else parts[-1]
            value = o[key] if isinstance(o, list) else o.get(key)
            if isinstance(value, str) and MARK.split(":")[0] in value:
                o[key] = next(text for name, text in kinds if name in parts[-1])
        return data

    def fact(self, *values):
        for v in values:
            if isinstance(v, (int, float)):
                self.facts.add(str(int(v)) if float(v).is_integer() else str(v))
            elif isinstance(v, str):
                for m in re.findall(r"\d+(?:[.,]\d+)?", v):
                    self.facts.add(m)

    # -- ortak hesaplar
    def coverage(self):
        return ((self.r.get("audit_status") or {}).get("content_coverage")) or {}

    def by_severity(self):
        """DECISIONS 301 (5): one source for every count, the client selection's; the report's own summary otherwise."""
        if self.sel is not None:
            return {k: v for k, v in self.sel["counts"]["by_severity"].items() if v}
        return ((self.r.get("problem_summary") or {}).get("by_severity")) or {}

    def sitemap_ratio(self):
        """IDX-5 paylı bulgu: (uygunsuz, kontrol edilen, listelenen, bulgu). Başlıktaki sayı esas alınır;
        kapsam alanı root_cause tarafından daraltılmış olabilir (bkz. kod incelemesi K15)."""
        for f in self.ordered:
            if f.get("check_id") != "IDX-5":
                continue
            # The engine's forms: "123 of 245 sitemap URL(s) [checked] (50%) are not live…" (checks/index.py) and, after
            # the evidence judgments, "123 sitemap URL observation(s) require differentiated review (245 checked)".
            title = f.get("title") or ""
            m = (re.search(r"(\d[\d,]*) of (\d[\d,]*) sitemap URL(?:s|\(s\))?(?: checked)?", title)
                 or re.search(r"(\d[\d,]*) sitemap URL observation\(s\) require differentiated review \((\d[\d,]*) checked\)", title))
            if m:
                listed = re.search(r"sitemap lists (\d[\d,]*)", f.get("title") or "")
                return num(m.group(1)), num(m.group(2)), num(listed.group(1)) if listed else None, f
        return None

    def lighthouse(self):
        for cid in ("DFS-9", "DFS-10", "DFS-11"):
            c = self.dfs.get(cid)
            data = ((c or {}).get("evidence") or {}).get("data") or {}
            metrics = data.get("metrics") or {}
            if c and c.get("status") in ("observed", "partial") and data.get("device", "mobile") == "mobile":
                score = metrics.get("Performance score (0–100)")
                return {"check_id": cid, "score": score, "metrics": metrics, "slow": data.get("past_good_threshold") or [],
                        "at": data.get("measurement_at") or (c.get("evidence") or {}).get("data_from")}
        return None

    def crux(self):
        c = self.r.get("crux") or {}
        return c if c.get("status") == "assessed" and c.get("metrics") else None

    def gaps(self):
        """Değerlendirilmeyen kısımlar. Müşteri seçimi varsa onun tek sayısı (`counts["not_assessed"]`,
        DECISIONS 305): KPI kutusu, kapsam satırı ve son sayfa aynı sayıyı basar. Yoksa aynı kural burada: aynı
        (kısım, neden) bir kez; okunmayan adresleri yeniden sayan kısımlar hariç (maya_audit.coverage.UNREAD_RESTATEMENTS,
        DECISIONS 283 (10)); cevap motoru paneli dahil."""
        if self.sel is not None and "not_assessed" in self.sel["counts"]:
            return self.sel["counts"]["not_assessed"]
        crawl_gap = unread_part_names()
        seen = set()
        for chk in (self.r.get("checks") or []) + (self.r.get("answer_engine_panel") or []):
            parts = ((chk.get("coverage") or {}).get("not_assessed")) or []
            if chk.get("status") == "not_assessed" and not parts:
                parts = [{"part": chk.get("title"), "reason": chk.get("summary")}]
            for p in parts:
                if p.get("part") in crawl_gap:
                    continue
                seen.add((p.get("part"), p.get("reason")))
        return len(seen)

    def saved_copies(self):
        rows = [p for p in (self.r.get("firecrawl") or {}).get("pages") or [] if p.get("outcome") == "read"]
        return sum(1 for p in rows if p.get("from_cache")), len(rows)

    def schema_additions(self):
        """Yapısal veri önerileri (Maya Audit P2): motorda Info ya da gözlem oldukları için yapılacaklara girmezler;
        burada tek kartta toplanır. Her satır: (tip, adresler, bulgu kimlikleri)."""
        rows = []
        for chk in self.r.get("checks") or []:
            if chk.get("check_id") != "STR-3":
                continue
            for o in chk.get("observations") or []:
                if o.get("metric") == "homepage with no WebSite structured data":
                    rows.append(("WebSite", list(o.get("examples") or [])[:1], ["STR-3"]))
            for f in chk.get("findings") or []:
                if f.get("id") in self.held:  # DECISIONS 300: under "Teyit edin", not on a Note card
                    continue
                if f.get("severity") != "Info":
                    continue
                title, urls = f.get("title") or "", [u for u in (f.get("scope") or {}).get("urls") or [] if isinstance(u, str)]
                if re.search(r"questions and answers but have no FAQPage", title):
                    rows.append(("FAQPage", urls, [f["id"]]))
                elif re.search(r"breadcrumb trail but have no BreadcrumbList", title):
                    rows.append(("BreadcrumbList", urls, [f["id"]]))
                elif re.search(r"lack the structured data type expected", title):
                    by_type = {}
                    for p in (f.get("evidence") or {}).get("pages") or []:
                        # sayfa türünden: beklenen tiplerin alfabetik ilki (ör. IndividualProduct) müşteriye yanlış tip söyler
                        want = KIND_SCHEMA.get(p.get("page_kind")) or ((p.get("expected_one_of") or ["?"])[0])
                        by_type.setdefault(want, []).append(p.get("url"))
                    rows += [(want, [u for u in us if u], [f["id"]]) for want, us in by_type.items()]
                elif re.search(r"Organization structured data has no", title):
                    what = ", ".join((f.get("evidence") or {}).get("missing") or [])
                    rows.append((f"Organization ({what})" if what else "Organization", urls, [f["id"]]))
        return rows

    def schema_card(self, i):
        """Tek «eklenebilecek yapısal veri» kartı, ya da öneri yoksa None."""
        rows = self.schema_additions()
        if not rows:
            return None
        L = self.L
        urls = list(dict.fromkeys(u for _, us, _ in rows for u in us))
        shown = urls[:4]
        src = "; ".join(f"{kind}: {len(us)} page(s)" + (f" ({', '.join(path_of(u) or '/' for u in us[:3])})" if us else "")
                        for kind, us, _ in rows)
        self.fact(*[len(us) for _, us, _ in rows], len(urls) - len(shown))
        ids = list(dict.fromkeys(i for _, _, fids in rows for i in fids))
        return {
            "n": i + 1, "id": " · ".join(ids[:3]), "finding_ids": ids, "severity": "Info", "severity_label": L["severity"]["Info"],
            "when": L["when"]["later"], "owner": L["owners"]["developer"], "effort": L["efforts"]["M"],
            "status": L["schema_card_status"],
            "title": self.slot(f"todos[{i}].title", "yapılacak işin adı, fiille başlar (yapısal veri ekleme)",
                               "Add the structured data these pages describe but do not mark up", 80,
                               prefill=NOTE_TEXT["schema"][self.lang][0]),
            "steps": self.slot(f"todos[{i}].steps", "2-4 somut adım; her tip ve hangi sayfa; her adım yeni satırda, en fazla 100 karakter",
                               src, 420, lines=4, fallback=T.note_steps([kind for kind, _, _ in rows], self.lang, platform=(self.sel or {}).get("platform"))),
            "verify": self.slot(f"todos[{i}].verify", "nasıl doğrulanır: hangi araç/adres ve orada ne görülmeli, tek cümle",
                                "Rich Results Test / Schema Markup Validator lists the added types without errors", 150,
                                prefill=NOTE_TEXT["schema"][self.lang][1]),
            "links": [{"href": u, "text": (path_of(u) if path_of(u) not in ("", "/") else urlsplit(u).netloc) or u} for u in shown],
            "more": max(0, len(urls) - len(shown)), "sitewide": not shown,
            "all_urls": urls, "known_paths": known_paths(src, urls),
        }

    HYGIENE_OBS = {
        ("IDX-3", "internal links pointing at redirecting URLs"): "internal links to redirecting addresses",
        ("STR-10", "pages with Open Graph tags but no twitter:card"): "no twitter:card",
        ("STR-10", "pages whose og:url names another address than their canonical"): "og:url differs from canonical",
        ("STR-10", "pages with an empty <meta name> tag"): "empty <meta> tags",
        ("IDX-6", "links to other sites that carry tracking or logged-in view parameters"): "parameters on links to other sites",
    }

    def hygiene_items(self):
        """Küçük düzeltmeler (Maya Audit P3): motorda gözlem ya da Info oldukları için yapılacaklara girmezler; burada
        tek kartta toplanır. Her satır: (konu, sayı, örnekler, adresler, kimlikler)."""
        rows = []
        for chk in self.r.get("checks") or []:
            cid = chk.get("check_id")
            for f in chk.get("findings") or []:
                if f.get("id") in self.held:  # DECISIONS 300: under "Teyit edin", not on a Note card
                    continue
                if cid == "ACC-8" and f.get("severity") == "Info" and "redirects" in (f.get("title") or ""):
                    moved = (f.get("evidence") or {}).get("redirecting") or []
                    ex = [path_of(m.get("url") if isinstance(m, dict) else m) for m in moved[:3]]
                    rows.append(("llms.txt links that redirect", len(moved), ex, [], [f["id"]]))
            for o in chk.get("observations") or []:
                label = self.HYGIENE_OBS.get((cid, o.get("metric")))
                if not label:
                    continue
                n = o.get("value") or o.get("pages") or o.get("links") or 0
                if label.startswith("internal links"):
                    ex = list(dict.fromkeys(path_of(s.get("target", "")) for s in (o.get("sample") or [])))[:3]
                    urls = []
                elif label.startswith("parameters"):
                    ex = [f"{urlsplit(e['url']).netloc} ({', '.join(e['parameters'][:2])})" for e in (o.get("examples") or [])[:3]]
                    urls = []
                elif label.startswith("empty"):
                    ex = [f"{k}: {v}" for k, v in (o.get("names") or {}).items()][:3]
                    urls = list(o.get("examples") or [])
                elif label.startswith("og:url"):
                    ex = [path_of(e["url"]) or "/" for e in (o.get("examples") or [])[:3]]
                    urls = [e["url"] for e in o.get("examples") or []]
                else:
                    ex, urls = [], list(o.get("examples") or [])
                rows.append((label, n, ex, urls, [cid]))
        return rows

    def hygiene_card(self, i):
        """Tek «küçük düzeltmeler» kartı, ya da konu yoksa None."""
        rows = self.hygiene_items()
        if not rows:
            return None
        L = self.L
        urls = list(dict.fromkeys(u for *_, us, _ in rows for u in us))
        shown = urls[:4]
        src = "; ".join(f"{label}: {n}" + (f" (e.g. {', '.join(e for e in ex if e)})" if any(ex) else "")
                        for label, n, ex, _, _ in rows)
        self.fact(*[n for _, n, *_ in rows], len(urls) - len(shown))
        ids = list(dict.fromkeys(i for *_, fids in rows for i in fids))
        return {
            "n": i + 1, "id": " · ".join(ids[:4]), "finding_ids": ids, "severity": "Info", "severity_label": L["severity"]["Info"],
            "when": L["when"]["later"], "owner": L["owners"]["developer"], "effort": L["efforts"]["S"],
            "status": L["hygiene_card_status"],
            "title": self.slot(f"todos[{i}].title", "yapılacak işin adı, fiille başlar (küçük düzeltmeler)",
                               "Clean up small link and tag inconsistencies", 80, prefill=NOTE_TEXT["hygiene"][self.lang][0]),
            "steps": self.slot(f"todos[{i}].steps", "2-4 somut adım; en önemlilerden başla; her adım yeni satırda, en fazla 100 karakter",
                               src, 420, lines=4, fallback=T.note_steps([label for label, *_ in rows], self.lang, platform=(self.sel or {}).get("platform"))),
            "verify": self.slot(f"todos[{i}].verify", "nasıl doğrulanır: hangi araç/adres ve orada ne görülmeli, tek cümle",
                                "The next Maya audit no longer lists these", 150, prefill=NOTE_TEXT["hygiene"][self.lang][1]),
            "links": [{"href": u, "text": (path_of(u) if path_of(u) not in ("", "/") else urlsplit(u).netloc) or u} for u in shown],
            "more": max(0, len(urls) - len(shown)), "sitewide": not shown,
            "all_urls": urls, "known_paths": known_paths(src, urls),
        }

    CONTENT_OBS = {
        ("STR-9", "pages whose header, menu or footer labels are in another language than the page"): "menu labels in another language",
        ("STR-2", "pages whose question-and-answer block writes its questions as plain text"): "questions not marked as headings",
        ("STR-14", "addresses whose words look misspelled against the page's own name"): "address words that look misspelled",
    }

    def draft_urls(self):
        """IDX-5'in taslak/test sayfaları: kendi kartlarında «kaldırın» denir, not kartlarında tekrar listelenmez."""
        return {u for f in self.findings.values() if f.get("check_id") == "IDX-5" and re.search(r"draft or test", f.get("title") or "")
                for u in (f.get("scope") or {}).get("urls") or []}

    def content_items(self):
        """İçerik ve dil düzeltmeleri (Maya Audit P4): motorda gözlem oldukları için yapılacaklara girmezler; burada
        tek kartta toplanır. Her satır: (konu, sayı, örnekler, adresler, kimlikler)."""
        rows = []
        for chk in self.r.get("checks") or []:
            cid = chk.get("check_id")
            for o in chk.get("observations") or []:
                label = self.CONTENT_OBS.get((cid, o.get("metric")))
                if not label:
                    continue
                examples = o.get("examples") or []
                if label.startswith("menu"):
                    ex = list(dict.fromkeys(l for e in examples for l in e.get("labels") or []))[:4]
                elif label.startswith("questions"):
                    ex = [path_of(e["url"]) or "/" for e in examples[:3]]
                else:
                    ex = [f"{path_of(e['url'])} ({e['address_word']} → {e['page_name_word']})" for e in examples[:3]]
                drafts = self.draft_urls()
                kept = [e for e in examples if e.get("url") not in drafts]
                if not kept and examples:
                    continue
                if label.startswith("questions"):
                    ex = [path_of(e["url"]) or "/" for e in kept[:3]]
                rows.append((label, (o.get("pages") or 0) - (len(examples) - len(kept)), ex,
                             [e["url"] for e in kept if e.get("url")], [cid]))
        return rows

    def content_card(self, i):
        """Tek «içerik ve dil düzeltmeleri» kartı, ya da konu yoksa None."""
        rows = self.content_items()
        if not rows:
            return None
        L = self.L
        urls = list(dict.fromkeys(u for *_, us, _ in rows for u in us))
        shown = urls[:4]
        src = "; ".join(f"{label}: {n} page(s)" + (f" (e.g. {', '.join(ex)})" if ex else "") for label, n, ex, _, _ in rows)
        self.fact(*[n for _, n, *_ in rows], len(urls) - len(shown))
        ids = list(dict.fromkeys(i for *_, fids in rows for i in fids))
        topics = {}  # the label's first word is its topic: menu, questions, address (CONTENT_OBS)
        for label, *_, fids in rows:
            topics.setdefault(label.split()[0], []).extend(fids)
        title, verify = topic_text("content", list(topics), self.lang)
        return {
            "n": i + 1, "id": " · ".join(ids[:4]), "finding_ids": ids, "severity": "Info", "severity_label": L["severity"]["Info"],
            "when": L["when"]["later"], "owner": L["owners"]["content"], "effort": L["efforts"]["S"],
            "status": L["content_card_status"],
            # DECISIONS 278: the release gate refuses a title topic no finding of this report supports (RG-11)
            "topics": [{"topic": t, "ids": v} for t, v in topics.items()],
            "title": self.slot(f"todos[{i}].title", "yapılacak işin adı, fiille başlar (içerik ve dil düzeltmeleri)",
                               topic_text("content", list(topics), "en")[0], 80, prefill=title),
            "steps": self.slot(f"todos[{i}].steps", "2-4 somut adım; adres değişikliğinde önce teyit, sonra kalıcı yönlendirme (sayı yazma); her adım yeni satırda, en fazla 100 karakter",
                               src, 420, lines=4, fallback=T.note_steps([label for label, *_ in rows], self.lang, platform=(self.sel or {}).get("platform"))),
            "verify": self.slot(f"todos[{i}].verify", "nasıl doğrulanır: hangi araç/adres ve orada ne görülmeli, tek cümle",
                                topic_text("content", list(topics), "en")[1], 150, prefill=verify),
            "links": [{"href": u, "text": (path_of(u) if path_of(u) not in ("", "/") else urlsplit(u).netloc) or u} for u in shown],
            "more": max(0, len(urls) - len(shown)), "sitewide": not shown,
            "all_urls": urls, "known_paths": known_paths(src, urls),
        }

    # Bilgi düzeyindeki bulgulardan PDF'e ayrı kartla girenler (DECISIONS 258): (kontrol, başlık kalıbı, konu adı).
    PERF_INFO = [
        ("PRF-1", r"not cached at the CDN", "HTML not cached at the CDN"),
        ("TSEO-1", r"script\(s\) in <head> without defer or async", "scripts in <head> without defer/async"),
        ("TSEO-1", r"same analytics tag more than once", "analytics tag loaded more than once"),
        ("STR-7", r"have no width and height", "images without width and height"),
        ("STR-7", r'declare type="image/jpg"', 'image preload with type="image/jpg"'),
        ("STR-7", r"reference WebP or AVIF", "no WebP or AVIF images"),
    ]
    SHARE_INFO = [
        ("STR-3", r"VideoObject that looks like an unfilled default", "VideoObject with default values"),
        ("STR-10", r"share image smaller than", "share image smaller than recommended"),
        ("STR-7", r"served in a format their file name does not say", "image format differs from its file name"),
    ]
    SHARE_TOPIC = {"VideoObject with default values": "video", "share image smaller than recommended": "share_image",
                   "image format differs from its file name": "image_format"}

    def info_items(self, table):
        rows = []
        for cid, pattern, label in table:
            for f in self.findings.values():
                if f.get("id") in self.held:  # DECISIONS 300: under "Teyit edin", not on a Note card
                    continue
                if f.get("check_id") != cid or f.get("severity") != "Info" or not re.search(pattern, f.get("title") or ""):
                    continue
                sc = f.get("scope") or {}
                urls = [u for u in sc.get("urls") or [] if isinstance(u, str)]
                n = sc.get("count") or len(urls) or num(f.get("title"))
                rows.append((label, n, [path_of(u) or "/" for u in urls[:3]], urls, [f["id"]], f.get("title") or ""))
        return rows

    def info_card(self, i, table, status_key, default_title, owner, kind=None):
        """Bilgi bulgularını tek kartta toplar (performans/etiket ya da paylaşım/şema), ya da konu yoksa None."""
        rows = self.info_items(table)
        if not rows:
            return None
        L = self.L
        urls = list(dict.fromkeys(u for *_, us, _, _ in rows for u in us))
        shown = urls[:4]
        src = "; ".join(f"{label}: {title}" for label, _, _, _, _, title in rows)
        self.fact(*[n for _, n, *_ in rows], len(urls) - len(shown))
        for *_, title in rows:
            self.fact(title)
        ids = [fid for *_, fids, _ in rows for fid in fids]
        topics = {}
        if kind in NOTE_TOPICS:  # a title that names topics names only those this report has (DECISIONS 278)
            for label, *_, fids, _ in rows:
                topics.setdefault(self.SHARE_TOPIC[label], []).extend(fids)
            title, verify = topic_text(kind, list(topics), self.lang)
        else:
            title, verify = NOTE_TEXT[kind][self.lang] if kind else (None, None)
        return {
            # three full IDs fit the card's one-line meta row; a fourth is clipped (seen on the Arjava render)
            "n": i + 1, "id": " · ".join(ids[:3]) + (f" +{len(ids) - 3}" if len(ids) > 3 else ""), "finding_ids": ids,
            "severity": "Info", "severity_label": L["severity"]["Info"],
            "when": L["when"]["later"], "owner": L["owners"][owner], "effort": L["efforts"]["M"],
            "status": L[status_key],
            "topics": [{"topic": t, "ids": v} for t, v in topics.items()],
            "title": self.slot(f"todos[{i}].title", "yapılacak işin adı, fiille başlar", default_title, 80, prefill=title),
            "steps": self.slot(f"todos[{i}].steps", "2-4 somut adım; en çok sayfayı etkileyenden başla, benzerleri birleştir; her adım yeni satırda, en fazla 100 karakter",
                               src, 420, lines=4, fallback=T.note_steps([label for label, *_ in rows], self.lang, platform=(self.sel or {}).get("platform"))),
            "verify": self.slot(f"todos[{i}].verify", "nasıl doğrulanır: hangi araç/adres ve orada ne görülmeli, tek cümle",
                                "The next Maya audit no longer lists these", 150, prefill=verify),
            "links": [{"href": u, "text": (path_of(u) if path_of(u) not in ("", "/") else urlsplit(u).netloc) or u} for u in shown],
            "more": max(0, len(urls) - len(shown)), "sitewide": not shown,
            "all_urls": urls, "known_paths": known_paths(src, urls),
        }

    def perf_card(self, i):
        return self.info_card(i, self.PERF_INFO, "perf_card_status", "Speed up and tidy how the pages load", "developer", "perf")

    def share_card(self, i):
        return self.info_card(i, self.SHARE_INFO, "share_card_status", "Fix share image, video markup and image formats", "developer", "share")

    # -- one card per cause (DECISIONS 284 (1))
    def manual_check(self, f):
        """The owner's confirmed manual check of this finding's group (review.json), or None."""
        g = ((self.sel or {}).get("by_finding") or {}).get(f.get("id")) or {}
        m = g.get("manual") or {}
        return m if m.get("result") == "confirmed" else None

    def merged_group(self, members):
        """The merge group (DECISIONS 301 (4)) of a card holding more than one finding, or None."""
        if len(members) < 2:
            return None
        try:
            from maya_audit.client_selection import MERGE_BY_RULE  # type: ignore
        except ImportError:
            return None
        return MERGE_BY_RULE.get(members[0].get("rule_id") or "")

    def members_of(self, f):
        """The findings on the card whose lead is `f` (the lead alone when it has no card of its own)."""
        return next((g for g in self.groups() if g[0] is f), [f])

    def merge_title(self, f):
        """A merged card's own title (DECISIONS 301 (4)) when `f` leads one, else None. The summary, the findings
        table and the action plan say the card's title and its whole scope, never the lead's (DECISIONS 305)."""
        merged = self.merged_group(self.members_of(f))
        return (merged["title"].get(self.lang) or merged["title"]["en"]) if merged else None

    def merge_finding(self, f):
        """What a merged card's findings say is wrong, in one line (`MERGE_GROUPS[...]["finding"]`), or None."""
        merged = self.merged_group(self.members_of(f))
        names = (merged or {}).get("finding") or {}
        return (names.get(self.lang) or names.get("en")) if names else None

    def rule_of(self, f):
        return f.get("rule_id") or self._w("rule")(f.get("check_id"), f.get("title"))

    @staticmethod
    def sections(f):
        """The site sections a finding is on: the engine's own `by_section`, else each address's first path segment."""
        rows = (f.get("evidence") or {}).get("by_section") or []
        if rows:
            return {r.get("section") for r in rows if r.get("section")}
        return {"/" + (path_of(u).strip("/").split("/")[0] + "/" if path_of(u).strip("/") else "")
                for u in (f.get("scope") or {}).get("urls") or [] if isinstance(u, str)}

    def same_cause(self, a, b):
        """One cause said twice: the engine's own dedup_key; IDX-1's repeated and single empty answers on the same
        sections; or two findings of one check whose cards would carry the same catalogue title."""
        if a.get("dedup_key") and a.get("dedup_key") == b.get("dedup_key"):
            return True
        ra, rb = self.rule_of(a), self.rule_of(b)
        if ra in EMPTY_RULES and rb in EMPTY_RULES and self.sections(a) & self.sections(b):
            return True
        if a.get("check_id") == b.get("check_id") and bool(a.get("intent")) == bool(b.get("intent")):
            ta, tb = self._w("action")(ra), self._w("action")(rb)
            return bool(ta) and ta == tb
        return False

    @staticmethod
    def retest_state(f):
        """A finding's second-look state; no record is "not re-tested" (that is what it means)."""
        return (f.get("verification") or {}).get("state") or "not_retested"

    def groups(self):
        """The findings in priority order, one list per card. A finding joins the first earlier card it shares a cause
        with, and only when both say the same about the re-test (a card shows one re-test state; RG-4)."""
        if getattr(self, "_groups", None) is None and self.sel is not None:
            self._groups = [g["members"] for g in self.sel["cards"]]
        if getattr(self, "_groups", None) is None:
            out = []
            for f in self.problems:
                home = next((g for g in out if any(self.same_cause(m, f) for m in g)
                             and {self.retest_state(m) for m in g} == {self.retest_state(f)}), None)
                if home is not None:
                    home.append(f)
                else:
                    out.append([f])
            self._groups = out
        return self._groups

    def sitemap_reasons(self, f):
        """[(reason, count)] for a sitemap finding that records a decision per address (`sitemap_decisions`), most
        first; [] for any other finding. Counted over the addresses under review, so the counts add up to its scope."""
        ev = f.get("evidence") or {}
        decisions = {d.get("url"): d for d in ev.get("sitemap_decisions") or [] if isinstance(d, dict)}
        urls = (ev.get("total_review_scope") or {}).get("urls") or (f.get("scope") or {}).get("urls") or []
        if not decisions or not urls:
            return []
        counts = {}
        for u in urls:
            d = decisions.get(u) or {}
            state, last = d.get("state"), (d.get("attempts") or [{}])[-1] or {}
            status = last.get("status") if isinstance(last.get("status"), int) else 0
            if state == "redirect_observed" or last.get("kind") == "redirect":
                key = "redirect_404" if ERROR_PAGE.search(last.get("location") or last.get("final_url") or "") else "redirect"
            elif state == "repeated_empty":
                key = "empty_repeated"
            elif state == "uncorroborated_empty" or last.get("kind") == "empty":
                key = "empty_single"
            elif state == "error_response" or status >= 400:
                key = "server_error" if status >= 500 else "not_found"
            elif state == "noindex_observed" or last.get("kind") == "noindex":
                key = "noindex"
            else:
                key = "other"
            counts[key] = counts.get(key, 0) + 1
        out = sorted(counts.items(), key=lambda kv: (-kv[1], SITEMAP_REASONS.index(kv[0])))
        self.fact(*[n for _, n in out])
        return out

    def reason_lines(self, f):
        unit = self.L["scope_units"]["url"]
        return [f"{fmt_int(n, self.lang)} {unit[0] if n == 1 else unit[1]} · {self.L['sitemap_reasons'][k][1]}"
                for k, n in self.sitemap_reasons(f)]

    def reason_title(self, f, maxlen):
        """The findings table's row for a sitemap finding: the reasons with counts, as many as fit."""
        reasons = self.sitemap_reasons(f)
        if not reasons:
            return None
        parts, more = [], self.L["sitemap_and_more"]
        for i, (k, n) in enumerate(reasons):
            part = self.L["sitemap_part"].format(n=fmt_int(n, self.lang), label=self.L["sitemap_reasons"][k][0])
            text = self.L["sitemap_row"].format(parts=", ".join(parts + [part]))
            tail = f" {more}" if i < len(reasons) - 1 else ""
            if len(text + tail) > maxlen and parts:
                return self.L["sitemap_row"].format(parts=", ".join(parts)) + f" {more}"
            parts.append(part)
        return self.L["sitemap_row"].format(parts=", ".join(parts))

    def group_scope(self, f):
        """A merged card's row in the findings table counts the addresses of all its findings, not only the lead's."""
        members = next((g for g in self.groups() if g[0] is f), [f])
        if len(members) < 2:
            return self.scope_text(f)
        # The full address list when the report has one (affected-urls.json); a finding's own list is cut short.
        lists = [self.affected.get(m["id"]) or (m.get("scope") or {}).get("urls") or [] for m in members]
        complete = all(len(urls) >= ((m.get("scope") or {}).get("count") or 0) for m, urls in zip(members, lists))
        n = (len({u for urls in lists for u in urls if isinstance(u, str)}) if complete
             else sum((m.get("scope") or {}).get("count") or 0 for m in members))
        unit = self.L["scope_units"]["url" if f.get("check_id") in URL_SCOPED and f.get("rule_id") not in PAGE_SCOPED_RULES else "page"]
        self.fact(n)
        return f"{fmt_int(n, self.lang)} {unit[0] if n == 1 else unit[1]}"

    def blocked_429_line(self, f):
        """DECISIONS 288: Maya's crawler blocked by 429 on pages. One line on the card: AI crawlers may be treated the same,
        and where to look (the blocker the evidence names, else the site's firewall)."""
        if self.rule_of(f) not in ("acc9.blocked_429", "acc9.rate_limited_429"):  # DECISIONS 288, 289
            return []
        named = next((b.get("name") for b in (f.get("evidence") or {}).get("blocked_by") or [] if b.get("name")), None)
        return [self.L["blocked_429_line"].format(who=named or self.L["blocked_429_firewall"])]

    def merged_lines(self, members):
        """One line per finding of a merged card: severity, scope and the finding's own title (DECISIONS 284 (1))."""
        if len(members) < 2:
            return []
        lines = []
        for m in members:
            text, _ = self.w.title(m.get("check_id"), m.get("title") or "")
            self.fact(m.get("title"))
            # The part before " — " says what was found; the rest lists examples, often in the engine's own words.
            # A title that starts with its count says the scope already ("2 sayfada …"): not twice.
            said = (text or m.get("title") or "").split(" — ")[0].rstrip(" ;,")
            scope = "" if re.match(r"\d", said) else f"{self.scope_text(m)} · "
            lines.append(f"{self.L['severity'][m['severity']]} · {scope}{said}")
        return lines

    def owner_effort(self, f):
        cid, title = f.get("check_id"), f.get("title") or ""
        engine = getattr(self.w, "owner", None)
        found = engine(cid, title) if callable(engine) else None
        if found and found[0] in self.L["owners"] and found[1] in self.L["efforts"]:
            return found
        for row in self.cat["by_title"].get(cid, []):
            if re.search(row["pattern"], title):
                return row["owner"], row["effort"]
        if cid in self.cat["by_check"]:
            v = self.cat["by_check"][cid]
            return v["owner"], v["effort"]
        rows = self.cat["by_title"].get(cid)
        if rows:
            return rows[0]["owner"], rows[0]["effort"]
        return self.cat["default"]["owner"], self.cat["default"]["effort"]

    def when(self, f):
        """maya_audit_web.practical.when ile aynı kural."""
        sev, effort = f.get("severity"), self.owner_effort(f)[1]
        if sev in ("S1", "S2") or (sev == "S3" and effort == "S"):
            return "week"
        if sev == "S3" or (sev == "S4" and effort == "S"):
            return "month"
        return "later"

    def scope_text(self, f):
        L, sc = self.L, f.get("scope") or {}
        ratio = self.sitemap_ratio()
        if ratio and ratio[3] is f:
            return f"{fmt_int(ratio[0], self.lang)} / {fmt_int(ratio[1], self.lang)} {self.L['scope_units']['url'][1]}"
        n = sc.get("count") or 0
        cid, title = f.get("check_id"), f.get("title") or ""
        if sc.get("kind") == "sitewide" and n <= 1:
            unit = "file" if re.search(r"sitemap file|robots\.txt|llms\.txt", title) else None
            return f"1 {L['scope_units']['file'][0]}" if unit else L["scope_units"]["site"]
        unit = "url" if cid in URL_SCOPED and f.get("rule_id") not in PAGE_SCOPED_RULES else "page"
        words = L["scope_units"][unit]
        return f"{fmt_int(n, self.lang)} {words[0] if n == 1 else words[1]}"

    def status_text(self, f, state=None):
        L = self.L
        ev = f.get("evidence") or {}
        check = self.manual_check(f)
        if check:  # DECISIONS 301 (1): the owner looked at it in a browser
            return L["manual_confirmed"].format(by=check.get("by"), date=check.get("date"))
        if ev.get("observation_strength") == "repeated_empty":
            parts = [L["repeated"]]
        else:
            parts = [L["confidence"].get(f.get("confidence"), f.get("confidence") or "")]
        # The engine's second look before the report (Maya Audit 1.19, DECISIONS 272). Since DECISIONS 278 a card also
        # says when it was not re-tested ("not_retested" is not a verdict, and a High card without it hid that).
        state = state or (f.get("verification") or {}).get("state")
        if state is None and f.get("severity") in ("S1", "S2"):
            state = "not_retested"
        if state in L.get("verification", {}):
            parts.append(L["verification"][state])
        if f.get("intent"):
            parts.append(L["intent_unverified"])
        # DECISIONS 300 (7): no "kontrol canlı sitelerde henüz doğrulanmadı" on a client card. A finding from a rule not
        # yet validated on real sites goes to "Teyit edin" (maya_audit.client_selection); the LG codes stay in
        # todos[].launch_gated as a trace, never in client text.
        return "; ".join(p for p in parts if p)

    def title_for(self, f, path, maxlen):
        text, engine = self.w.title(f.get("check_id"), f.get("title") or "")
        self.fact(f.get("title"))
        by_reason = self.reason_title(f, maxlen)
        library = self.lib(f, merged=False)["finding"]
        if by_reason:
            return self.slot(path, "bulgu başlığı", f.get("title"), maxlen, prefill=by_reason, fallback=library)
        if text and self.lang == "en":
            return self.slot(path, "bulgu başlığı (kısa, sayısız ya da rapordaki sayıyla)", f.get("title"), maxlen,
                             prefill=_short(text), fallback=library)
        if text and engine:
            return self.slot(path, "bulgu başlığı", f.get("title"), maxlen, prefill=_short(text), fallback=library)
        return self.slot(path, "bulgu başlığı, kısa", f.get("title"), maxlen, fallback=library)

    # -- sayfalar
    def build(self):
        L, lang, r = self.L, self.lang, self.r
        crawl = r.get("crawl") or {}
        gen = r.get("generation") or {}
        cov = self.coverage()
        sev = self.by_severity()
        ps = r.get("problem_summary") or {}
        origin = crawl.get("origin") or crawl.get("start_url") or ""
        domain = urlsplit(origin).netloc or origin
        brand = ((r.get("brand") or {}).get("name")) or domain
        started = crawl.get("started_at") or gen.get("native_started_at")
        audit_id = self.audit_id or (r.get("dataforseo") or {}).get("audit_id") or "—"
        version = gen.get("engine_version") or "—"
        ratio, lab, crux = self.sitemap_ratio(), self.lighthouse(), self.crux()
        market = None
        dfs4 = self.dfs.get("DFS-4")
        if dfs4:
            m = re.search(r"\(([^()]+)\)\s*$", dfs4.get("title") or "")
            market = m.group(1).replace(", ", " / ") if m else None
            if market and lang == "tr":
                for en_name, tr_name in COUNTRIES_TR.items():
                    market = market.replace(en_name, tr_name)

        problems_total = self.sel["counts"]["problems"] if self.sel is not None else ps.get("problems", len(self.problems))
        notes_total = self.sel["counts"]["by_severity"]["Info"] if self.sel is not None else ps.get("notes", 0)
        self.fact(problems_total, *[sev.get(k, 0) for k in SEVERITIES], notes_total)
        sev_line = " · ".join(f"{sev.get(k, 0)} {L['sev_lower'][k]}" for k in SEVERITIES if sev.get(k))
        pages_read, unread = cov.get("pages_read") or 0, cov.get("known_urls_not_read") or 0
        self.fact(pages_read, unread)

        kpis = [
            {"label": L["kpi_problems"], "value": fmt_int(problems_total, lang), "of": None, "sub": sev_line or "—", "state": "ok"},
            {"label": L["kpi_pages"], "value": fmt_int(pages_read, lang), "of": None,
             # Nothing read and nothing left unread is not "every page was read" (nihan.com.tr: 429 on the first request).
             "sub": L["kpi_pages_sub"].format(n=fmt_int(unread, lang)) if unread else
             L["kpi_pages_sub_all"] if pages_read else L["kpi_pages_sub_none"], "state": "ok" if pages_read else "missing"},
        ]
        if ratio:
            bad, checked, listed, f = ratio
            self.fact(bad, checked, listed)
            kpis.append({"label": L["kpi_sitemap"], "value": fmt_int(bad, lang), "of": fmt_int(checked, lang),
                         "sub": L["kpi_sitemap_sub"].format(conf=L["confidence"].get(f.get("confidence"), "")), "state": "ok"})
        elif pages_read:
            # yalnız gerçekten okunan sayfalar: yoklanıp okunmayan adresler paydayı aşmasın
            # (DECISIONS 287: nothing read, no "0 / 0" tile; the pages box already says nothing could be read)
            read = self.read_urls()
            # DECISIONS 283 (2): the headline counts pages with a Medium or higher page-specific problem; a page whose
            # only problems are Low is not a "page with problems" there (Carpex showed 145/146).
            pages_with = sum(1 for row in ps.get("by_page") or []
                             if (not read or row.get("url") in read) and self.worst(row) in MEDIUM_UP)
            # by_page holds page-specific problems only; shared header/footer and site-wide ones are counted once under
            # whole_site. Say so, or a card listing every page reads as a contradiction of this number.
            whole = int((ps.get("whole_site") or {}).get("problems") or 0)
            self.fact(pages_with, whole)
            kpis.append({"label": L["kpi_problem_pages"], "value": fmt_int(pages_with, lang), "of": fmt_int(pages_read, lang),
                         "sub": L["kpi_problem_pages_sub_whole"].format(n=fmt_int(whole, lang)) if whole else L["kpi_problem_pages_sub"],
                         "state": "ok"})
        if lab and lab.get("score") is not None:
            self.fact(lab["score"])
            kpis.append({"label": L["kpi_lab"], "value": str(lab["score"]), "of": "100", "sub": L["kpi_lab_sub"], "state": "ok"})
        else:
            kpis.append({"label": L["kpi_lab"], "value": L["not_measured"], "of": None, "sub": L["not_measured_sub"], "state": "missing"})

        # öncelikler: en önemli 3 kontrol grubu; mobil lab zayıfsa 3. sırayı alır
        # "kasıtlı olabilir" (intent) işaretli bulgular öncelik listesine girmez: önce teyit edilmeleri gerekir.
        groups, seen = [], set()
        # DECISIONS 300: the priorities are the first cards (a finding to confirm first is never a priority).
        source = [g["lead"] for g in self.sel["cards"] if g["severity"] in SEVERITIES] if self.sel is not None else self.problems
        for f in source:
            if f.get("intent") or f["check_id"] in seen:
                continue
            seen.add(f["check_id"])
            groups.append(f)
        lab_poor = bool(lab and isinstance(lab.get("score"), (int, float)) and lab["score"] < 50)
        chosen = groups[:3]
        if lab_poor and (len(chosen) < 3 or chosen[2].get("severity") in ("S3", "S4")):
            chosen = chosen[:2] + ["perf"]
        priorities = []
        for i, f in enumerate(chosen):
            if f == "perf":
                self.fact(*[str(lab["metrics"].get(m) or "") for m in lab["slow"]])
                page1 = T.library(lang)["page1"]
                priorities.append({"n": i + 1, "tone": "accent", "value": f"{lab['score']} / 100", "finding_ids": [lab["check_id"]],
                                   "title": self.slot(f"priorities[{i}].title", "odak alanı adı (2-4 kelime)", "mobile lab performance", 40,
                                                      fallback=page1["priority_perf_title"]),
                                   "text": self.slot(f"priorities[{i}].text", "tek cümle: ne yapılmalı",
                                                     "Lighthouse: " + ", ".join(lab["slow"]) + " past threshold", 150,
                                                     fallback=page1["priority_perf_text"])})
                continue
            tone = "high" if f["severity"] in ("S1", "S2") else "medium" if f["severity"] == "S3" else "low"
            self.fact(f.get("title"))
            merged = self.merge_title(f)
            members = self.members_of(f)
            priorities.append({"n": i + 1, "tone": tone, "value": self.group_scope(f),
                               "finding_ids": [m["id"] for m in members],
                               "title": self.slot(f"priorities[{i}].title", "odak alanı adı (2-4 kelime)",
                                                  merged or f.get("title"), 40, fallback=self.lib(f)["summary"]),
                               "text": self.slot(f"priorities[{i}].text", "tek cümle: ne yapılmalı / ne doğrulanmamış",
                                                 (self.merged_group(members) or {}).get("fix", {}).get("en") or f.get("how_to_fix"), 150,
                                                 fallback=T.priority_text(self.lib(f), self.confidence_of(f),
                                                                          bool(self.manual_check(f)), lang))})

        saved, read_fc = self.saved_copies()
        gaps = self.gaps()
        self.fact(saved, read_fc, gaps, sev.get("S1", 0))
        coverage_box = {
            "badge": L["badge_saved"] if saved else L["badge_live"],
            "rows": [
                {"label": L["cov_gaps"], "value": fmt_int(gaps, lang)},
                # DECISIONS 306: a row that would say 0 (no page read from a saved copy) is not printed.
                *([{"label": L["cov_saved"], "value": f"{saved} / {read_fc} {L['scope_units']['page'][1]}"}] if saved else []),
                {"label": L["cov_notes"], "value": fmt_int(notes_total, lang)},
                {"label": L["cov_blockers"], "value": fmt_int(sev.get("S1", 0), lang)},
            ],
            "note": L["cov_note"],
        }

        # sayfa 2
        leads = [g[0] for g in self.groups()]
        top = leads[:5]
        # DECISIONS 306: the findings table says what is wrong (a merged card's `finding` name); the cards say what to do.
        findings = [{"id": f["id"], "title": (self.slot(f"findings[{i}].title", "bulgu başlığı (ne yanlış; eylem değil)",
                                                        f.get("title"), 70, prefill=self.merge_finding(f))
                                              if self.merge_finding(f) else self.title_for(f, f"findings[{i}].title", 70)),
                     "scope": self.group_scope(f), "severity": f["severity"], "severity_label": L["severity"][f["severity"]],
                     "status": self.status_text(f)} for i, f in enumerate(top)]
        for f in self.problems:
            self.fact(f.get("how_to_fix"), f.get("title"))
        sample = self.evidence_sample(top[0]) if top else None
        first_fix = (top[0].get("how_to_fix") if top else "") or ""
        fix_text, _ = self.w.fix(first_fix)
        # DECISIONS 307: the next step, the caveat, the verdict and the assessment are built from the top problem
        # cards with the text library's page-1 templates; their numbers and order are the selection's.
        card_leads = [f for f in leads if f.get("severity") in SEVERITIES]
        first = self.lib(card_leads[0]) if card_leads else None
        summaries = [self.lib(f)["summary"] for f in card_leads]
        has_confirm = bool((self.sel or {}).get("confirm"))
        page1 = T.library(lang)["page1"]
        next_action = {
            "lead": self.slot("next_action.lead", "kalın giriş, tek kısa cümle", first_fix, 60,
                              fallback=T.lead(first, lang) if first else page1["next_none"]),
            "text": self.slot("next_action.text", "devam cümlesi: nasıl doğrulanır / sonra ne", fix_text or first_fix, 200,
                              fallback=T.next_text(first, summaries[1:], lang) if first else page1["next_none"]),
            "caveat": self.slot("next_action.caveat", "kanıtın sınırı, tek cümle (ör. neyin doğrulanmadığı)", None, 170,
                                fallback=T.caveat(reanalysis=self.reanalysis, has_confirm=has_confirm, has_cards=bool(first),
                                                  first_confidence=self.confidence_of(card_leads[0]) if first else None,
                                                  lang=lang)),
        }

        # sayfa 3
        search = self.search()
        lab_box = None
        if lab:
            diags = []
            for name in lab["slow"]:
                diags.append({"label": LAB_LABELS.get(name, {}).get(lang, name), "value": lab_value(lab["metrics"].get(name), lang)})
                self.fact(str(lab["metrics"].get(name) or ""))
            lab_box = {"score": lab["score"], "date": date_long(lab["at"], L), "diagnostics": diags}
        field = None
        if crux:
            field = {"pass": bool(crux.get("passes_core_web_vitals")),
                     "rows": [{"label": m.get("label") or m.get("metric"), "value": m.get("shown"), "rating": m.get("rating")}
                              for m in crux.get("metrics") or []],
                     "until": crux.get("data_until")}
            for m in crux.get("metrics") or []:
                self.fact(str(m.get("shown") or ""))
        limits = {"text": FIXED["limits"][lang] if lab else L["lab_none"],
                  "action": FIXED["limits_action"][lang] if lab else
                  ("Performance remains unassessed; obtain comparable lab and field evidence if needed."
                   if lang == "en" else "Performans değerlendirilmedi; gerekirse karşılaştırılabilir laboratuvar ve saha kanıtı alınmalıdır.")}

        # sayfa 4
        # kasıtlı olabilecek bulgular haftanın aksiyonlarında en sona alınır (ilk iş "teyit et" olur)
        week = sorted((f for f in leads if self.when(f) == "week"), key=lambda f: bool(f.get("intent")))
        if self.sel is not None:
            # DECISIONS 300: the action table is the first five cards in priority order, whatever their week.
            week = [f for f in leads if f.get("severity") in SEVERITIES]
        month = [f for f in leads if self.when(f) == "month"]
        later = [f for f in leads if self.when(f) == "later"]
        actions = []
        for f in week:
            if len(actions) >= 5:
                break
            if lab_poor and not any("DFS" in a["ref"] for a in actions) and f["severity"] not in ("S1", "S2"):
                actions.append(self.perf_action(lab, len(actions)))
                if len(actions) >= 5:
                    break
            owner, effort = self.owner_effort(f)
            i = len(actions)
            fx, _ = self.w.fix(f.get("how_to_fix") or "")
            actions.append({"n": i + 1, "ref": f["id"], "owner": L["owners"][owner], "effort": L["efforts"][effort],
                            "title": self.slot(f"actions[{i}].title", "aksiyon cümlesi, fiille başlar, kısa",
                                               (fx or f.get("how_to_fix") or f.get("title")), 75,
                                               prefill=self.merge_title(f) or
                                               self._w("action")(f.get("rule_id") or self._w("rule")(f.get("check_id"), f.get("title"))),
                                               fallback=self.lib(f)["title"])})
        if lab_poor and len(actions) < 5 and not any("DFS" in a["ref"] for a in actions):
            actions.append(self.perf_action(lab, len(actions)))
        self.fact(len(month), len(later))
        followup = {
            "count": len(month),
            "text": self.slot("followup.text", "bu ayki işlerin 1-2 cümlelik özeti", "; ".join(f.get("title") for f in month[:8]), 170,
                              fallback=T.followup([self.lib(f)["summary"] for f in month], lang))
            if month else "—",
            "note": L["followup_note"],
        }
        later_rows = []
        for i, f in enumerate(later[:3]):
            cnt = (f.get("scope") or {}).get("count") or 1
            self.fact(cnt, f.get("title"))
            text, engine = self.w.title(f.get("check_id"), f.get("title") or "")
            prefill = _strip_count(text) if text and (engine or lang == "en") else None
            if prefill and (len(prefill) > 55 or re.search(r"\d", prefill)):
                prefill = None  # sayı içeren ya da uzun motor metni: model kısaltır
            if not prefill:
                act = self._w("action")(f.get("rule_id") or self._w("rule")(f.get("check_id"), f.get("title")))
                prefill = act if act and len(act) <= 55 else None
            unit = L["scope_units"]["url" if f.get("check_id") in ("IDX-1", "IDX-6", "IDX-3", "IDX-5") else "page"]
            later_rows.append({"count": f"{fmt_int(cnt, lang)} {unit[0] if cnt == 1 else unit[1]}",
                               "label": self.slot(f"later[{i}].label", "kısa etiket, sayı olmadan", f.get("title"), 55, prefill=prefill,
                                                  fallback=next(t for t in (self.lib(f)["title"], self.lib(f)["summary"])
                                                                if len(t) <= 55 or t == self.lib(f)["summary"]))})

        # yapılacaklar (ek sayfalar): bütün sorunlar, takvim sırasıyla; kasıtlı olabilecekler kendi grubunun sonunda
        todos = []
        not_listed = {row.get("finding_id"): int(row.get("pages") or 0) for row in ps.get("not_listed") or []}
        # DECISIONS 300: one card per root cause, in priority order (severity x confidence x reach x business), at most
        # 15; the order is the selection's. Without a selection (an engine before 300), by "when" as before.
        if self.sel is not None:
            ordered = [(self.when(m[0]), m) for m in self.groups()]
        else:
            ordered = []
            for when_key in ("week", "month", "later"):
                bucket = [g for g in self.groups() if self.when(g[0]) == when_key]
                bucket.sort(key=lambda g: bool(g[0].get("intent")))
                ordered += [(when_key, g) for g in bucket]
        by_lead = {g["finding_ids"][0]: g for g in (self.sel or {}).get("cards") or []}
        for when_key, members in ordered:
            if True:
                f = members[0]  # the card's lead: the first in priority order
                group = by_lead.get(f["id"]) or {}
                i = len(todos)
                owner, effort = self.owner_effort(f)
                sc = f.get("scope") or {}
                url_finding = {}
                for m in members:
                    for u in ((m.get("scope") or {}).get("urls") or []) + self.affected.get(m["id"], []):
                        if isinstance(u, str):
                            url_finding.setdefault(u, m["id"])
                # One example per language first (TR and EN on one card, DECISIONS 300 (1)), then the rest.
                examples = [x["url"] for x in group.get("examples") or [] if x.get("url") in url_finding]
                urls = examples + [u for u in url_finding if u not in examples]
                sub = self.merged_lines(members) or self.reason_lines(f) or self.blocked_429_line(f)
                # DECISIONS 305: addresses that were not read add nothing to the score; the card says how many.
                if group.get("addresses_not_read"):
                    sub = list(sub or []) + [L["not_read_line"].format(n=fmt_int(group["addresses_not_read"], self.lang))]
                    self.fact(group["addresses_not_read"])
                # kartta 4 link (satırlı kartta 2: satırlar yer kaplar); tam liste render.py'nin yazdığı adres listesi CSV'sinde
                shown = urls[:2 if sub else 4]
                # listelenip kartta gösterilmeyenler + rapordaki listeye hiç girmeyen sayfalar (problem_summary.not_listed)
                unlisted = max(0 if m["id"] in self.affected else not_listed.get(m["id"], 0) for m in members)
                more = max(0, len(urls) - len(shown)) + unlisted
                fx, fx_ok = self.w.fix(f.get("how_to_fix") or "")
                ex, ex_ok = self.w.expected(f.get("expected") or "")
                # DECISIONS 270: kural kataloğu ve motorun kendi çevirisi kartı doldurur; sığmayan alan modele kalır.
                rule = f.get("rule_id") or self._w("rule")(f.get("check_id"), f.get("title"))
                action = self._w("action")(rule)
                step_rules = getattr(self.w, "step_rules", None)
                pre_steps, conditional = step_rules(rule, members) if step_rules else (self._w("steps")(rule), [])
                pre_steps = pre_steps or (steps_from(fx) if fx and (fx_ok or self.lang == "en") else None)
                # Shopify writes its own sitemap, so the lastmod card's steps say what to do there (DECISIONS 300 (7)).
                platform = (self.sel or {}).get("platform")
                on_platform = platform_steps(rule, platform, self.lang) if self.sel is not None else None
                if on_platform:
                    pre_steps, conditional = "\n".join(on_platform), []
                # DECISIONS 284 (1): a merged card also takes the other findings' own catalogue steps, while they fit.
                for m in members[1:]:
                    other = self.rule_of(m)
                    if not pre_steps or other == rule:
                        continue
                    more_steps, more_rules = step_rules(other, [m]) if step_rules else (self._w("steps")(other), [])
                    lines = pre_steps.split("\n")
                    for line in (more_steps or "").split("\n"):
                        if line.strip() and line not in lines and len(lines) < STEP_LINES:
                            lines.append(line)
                    pre_steps = "\n".join(lines)
                    conditional = conditional + [c for c in more_rules if c.get("text") in lines]
                pre_verify = first_upper(ex, self.lang).rstrip(".") + "." if ex and (ex_ok or self.lang == "en") else None
                # Maya Audit P2: bozuk bloğun düzelince de eksik kalacak önerilen alanları (ör. logo, sameAs)
                lacking = (f.get("evidence") or {}).get("recommended_still_lacking") or []
                if lacking:
                    fx = f"{fx or f.get('how_to_fix') or ''} | Also add when fixing (missing even once it parses): {', '.join(lacking)}"
                    extra = (f"Düzeltirken {', '.join(lacking)} alanlarını da ekleyin" if self.lang == "tr"
                             else f"Also add {', '.join(lacking)} when fixing")
                    pre_steps = (pre_steps + "\n" + extra) if pre_steps and pre_steps.count("\n") < STEP_LINES - 1 else None
                self.fact(sc.get("count"), more, pre_steps, pre_verify)
                states = [(m.get("verification") or {}).get("state") for m in members]
                state = states[0] if len(set(states)) == 1 else self.retest_state(f)
                merged = self.merged_group(members)
                found = next(((m.get("evidence") or {}).get("regions") for m in members if (m.get("evidence") or {}).get("regions")), None)
                if found:
                    from maya_audit import language_regions  # type: ignore
                    region_advice = language_regions.advice(found, (self.sel or {}).get("platform"), self.lang)
                    if region_advice:
                        pre_steps, conditional = "\n".join(region_advice), []
                    where = language_regions.line(found, L["region_names"])
                    if where:
                        sub = [L["regions_line"].format(regions=where)] + list(sub or [])
                        self.fact(where)
                check = self.manual_check(f)
                if check and check.get("note"):
                    sub = [L["manual_note"].format(note=check["note"])] + list(sub or [])
                if merged and not found:
                    action = merged["title"].get(self.lang) or merged["title"]["en"]
                if pre_steps:
                    # A merged card collects its members' catalogue steps: drop one that says the same as an earlier
                    # one (same first three words), and keep three when the card already shows two or more lines
                    # above its steps (the card's box has room for no more; DECISIONS 301 (4)).
                    kept, heads = [], set()
                    for step_line in pre_steps.split("\n"):
                        head = " ".join(step_line.lower().split()[:3])
                        if step_line.strip() and head not in heads:
                            heads.add(head)
                            kept.append(step_line)
                    pre_steps = "\n".join(kept[:3] if len(sub or []) >= 2 else kept)
                if group:
                    self.fact(group.get("priority"))
                # DECISIONS 307: what the catalogue and the engine do not say, the text library does (the platform's own
                # steps when the site runs on it).
                entry = self.lib(f)
                lib_steps, lib_platform = T.steps(entry, platform)
                title_v = self.slot(f"todos[{i}].title", "yapılacak işin adı, fiille başlar", f.get("title"), 80, prefill=action,
                                    fallback=entry["title"])
                steps_v = self.slot(f"todos[{i}].steps", "2-4 somut adım; her adım yeni satırda, en fazla 100 karakter",
                                    fx or f.get("how_to_fix"), 420, lines=4, prefill=pre_steps, fallback="\n".join(lib_steps))
                verify_v = self.slot(f"todos[{i}].verify", "nasıl doğrulanır: hangi araç/adres ve orada ne görülmeli, tek cümle",
                                     ex or f.get("expected"), 150, prefill=pre_verify, fallback=entry["verify"])
                # RG-11 compares the platform a card's steps were written for with the report's platform.
                shown_platform = (platform if on_platform and steps_v == pre_steps else
                                  lib_platform if lib_platform and steps_v == "\n".join(lib_steps) else None)
                if steps_v != pre_steps:
                    conditional = []  # the catalogue's conditional steps are not on the card
                todos.append({
                    "n": i + 1, "id": " · ".join(m["id"] for m in members[:2]) + (f" +{len(members) - 2}" if len(members) > 2 else ""),
                    # DECISIONS 300: the card's place and score in Maya Audit's client selection (shown, never a severity)
                    "priority": group.get("priority"), "confidence_class": group.get("confidence"),
                    "platform_steps": shown_platform,
                    "finding_ids": [m["id"] for m in members],
                    "severity": f["severity"], "severity_label": L["severity"][f["severity"]],
                    # The release gate (DECISIONS 278) compares what the card shows with the finding's own state.
                    "verification_state": state,
                    "when": L["when"][when_key], "owner": L["owners"][owner], "effort": L["efforts"][effort],
                    "status": self.status_text(f, state),
                    "sub": sub,
                    "rule_id": rule,
                    "fact": fact_line(self._w("facts")(rule, f.get("evidence")), L),
                    "known_paths": sorted({p for m in members for p in known_paths(m.get("title"), m.get("scope"), m.get("evidence"),
                                                                                     m.get("how_to_fix"))}),
                    "title": title_v, "steps": steps_v, "verify": verify_v,
                    "links": [{"href": u, "text": (path_of(u) if path_of(u) not in ("", "/") else urlsplit(u).netloc) or u} for u in shown],
                    "more": more, "sitewide": not shown,
                    "all_urls": urls, "unlisted": unlisted, "step_rules": conditional,
                    "url_finding": url_finding if len(members) > 1 else {},
                    # DECISIONS 278: a broken link's failing addresses, shown apart from the pages to edit
                    "target_urls": list(dict.fromkeys(u for m in members for u in (m.get("evidence") or {}).get("target_urls") or [])),
                    # DECISIONS 283: one row per link to edit, from the final result
                    "link_rows": [row for m in members for row in link_rows(self.cards.get(m["id"]))],
                    "launch_gated": sorted({g for m in members for g in m.get("launch_gated") or [] if re.fullmatch(r"LG-\d+", str(g))}),
                })
                self.fact(todos[-1]["fact"])  # a card may quote its evidence's numbers
        for make in (self.schema_card, self.hygiene_card, self.content_card, self.perf_card, self.share_card):
            if self.sel is not None and len(todos) >= MAX_CARDS:
                break  # DECISIONS 300: at most 15 cards; the notes are in the appendix in any case
            card = make(len(todos))
            if card:
                todos.append(card)

        extra = self.client_page(todos) if self.sel is not None else {}

        listed = ratio[2] if ratio else None
        checked = ratio[1] if ratio else None
        prov = [{"k": L["prov_content"], "v": L["prov_content_line"].format(read=fmt_int(pages_read, lang), unread=fmt_int(unread, lang), gaps=gaps)}]
        if ratio and listed:
            prov.append({"k": L["prov_sitemap"], "v": L["prov_sitemap_line"].format(listed=fmt_int(listed, lang), checked=fmt_int(checked, lang))})
        prov.append({"k": L["prov_engine"], "v": L["prov_engine_line"].format(version=version, audit_id=audit_id)})
        # DECISIONS 308: a saved audit re-evaluated with the current engine says so, with that engine and its date.
        from maya_audit_web.team_report.current import line_of
        reassessed = (line_of((gen.get("analysis") or {}).get("engine"), lang) if not gen.get("_reassess_failed")
                      else L["prov_reassess_failed"])
        if reassessed:
            prov.append({"k": L["prov_reassessed"], "v": reassessed})
            self.fact(reassessed)

        data = {
            "contract": 1, "lang": lang,
            "meta": {"brand": brand, "domain": domain, "date": date_short(started, L), "date_long": date_long(started, L),
                     "revision": self.rev, "audit_id": audit_id, "engine_version": version, "market": market,
                     "coverage_level": cov.get("level") or "partial",
                     "coverage_label": L["coverage_level"].get(cov.get("level") or "partial", cov.get("level"))},
            "kpis": kpis,
            "assessment": {"headline": self.slot("assessment.headline", "raporun tek cümlelik hükmü", None, 90,
                                                 fallback=T.headline([f["severity"] for f in card_leads], summaries, lang,
                                                                     pages_read=pages_read)),
                           "text": self.slot("assessment.text", "hangi sırayla ne yapılmalı, tek cümle", None, 190,
                                             fallback=T.assessment(summaries, has_confirm, lang))},
            "priorities": priorities,
            "coverage": coverage_box,
            "findings": findings,
            "evidence_sample": sample,
            "next_action": next_action,
            "search": search,
            "lab": lab_box,
            "field": field,
            "commercial": FIXED["commercial"][lang],
            "limits": limits,
            "actions": actions,
            "actions_schedule": L["schedule_priority"] if self.sel is not None else L["schedule_label"].format(when=L["when"]["week"]),
            "followup": followup,
            "later": later_rows,
            "todos": todos,
            **extra,
            "provenance": {"lines": prov, "note": L["prov_note_saved"] if self.reanalysis else
                           (L["prov_note_cache"].format(saved=saved, read=read_fc) if saved else L["prov_note_live"])},
        }
        self.fact(started or "")
        self.finish(data)
        data["_slots"] = self.slots
        data["_facts"] = sorted(self.facts)
        data["_engine_wording"] = self.w.mod is not None
        return data

    def client_page(self, todos):
        """DECISIONS 300: the last page's content — Maya's own limits (coverage), "Teyit edin", the key pages scorecard,
        the quick wins and the appendix pointer with its counts. Every number comes from the selection."""
        L, lang, sel = self.L, self.lang, self.sel
        c = sel["counts"]
        cov = sel["coverage"]
        limits = []
        for line in cov["lines"]:
            if line["kind"] == "page_cap":
                limits.append(L["own_page_cap"].format(pages=fmt_int(line.get("pages") or 0, lang),
                                                       not_read=fmt_int(line.get("not_read") or 0, lang)))
                self.fact(line.get("pages"), line.get("not_read"))
            elif line["kind"] == "time_budget":
                limits.append(L["own_time"].format(seconds=fmt_int(int(line.get("seconds") or 0), lang)))
                self.fact(int(line.get("seconds") or 0))
            elif line["kind"] == "reader":
                text, _ = self.w.title(None, line.get("title") or "")
                limits.append(text or line.get("title"))
                self.fact(line.get("title"))
        gaps = self.gaps()
        if gaps:
            limits.append(L["own_gaps"].format(n=fmt_int(gaps, lang)))
            self.fact(gaps)
        confirm = []
        for i, g in enumerate(sel["confirm"][:CONFIRM_SHOWN]):
            f = g["lead"]
            text, engine = self.w.title(f.get("check_id"), f.get("title") or "")
            self.fact(f.get("title"))
            scope = self.group_scope(f) if g["severity"] != "Info" else self.scope_text(f)
            self.fact(scope)
            title = self.slot(f"confirm[{i}].title", "teyit edilecek bulgunun kısa adı", f.get("title"), 90,
                              prefill=_short(text) if text and (engine or lang == "en") and len(_short(text)) <= 90 else None,
                              fallback=T.confirm_title(self.lib(f, merged=False), None, lang))
            confirm.append({"title": title, "severity": g["severity"], "severity_label": L["severity"].get(g["severity"], g["severity"]),
                            "reason": L["confirm_reasons"][g["confirm_reason"]], "finding_ids": g["finding_ids"],
                            "scope": self.group_scope(f) if g["severity"] != "Info" else self.scope_text(f)})
        more_confirm = max(0, len(sel["confirm"]) - CONFIRM_SHOWN)
        pages = []
        for p in sel["key_pages"]:
            self.fact(p["rank"], p["importance"], p["confirm"], *p["cards"])
            pages.append({"rank": p["rank"], "path": path_of(p["url"]) or urlsplit(p["url"]).netloc, "url": p["url"],
                          "type": L["page_types"].get(str(p["page_type"]), "—"), "importance": p["importance"],
                          "cards": ", ".join(f"{n:02d}" for n in p["cards"]) or "—",
                          "worst": L["severity"].get(p["worst"], "—") if p["worst"] else "—", "confirm": p["confirm"]})
        try:  # DECISIONS 306: a fix that renames addresses (redirects) is never a quick win
            from maya_audit.recommendation_catalog import RENAMES_ADDRESSES  # type: ignore
        except ImportError:
            RENAMES_ADDRESSES = frozenset()
        quick = [t["n"] for t in todos if t.get("effort") == L["efforts"]["S"] and t.get("finding_ids")
                 and t.get("rule_id") not in RENAMES_ADDRESSES][:4]
        name = L["appendix_file"]
        self.fact(*c.values(), more_confirm)
        reason = sel.get("key_pages_reason")
        return {"own_limits": limits, "confirm": confirm, "confirm_more": more_confirm, "key_pages": pages,
                "key_pages_note": L["key_pages_empty"][reason] if reason and not pages else None,
                "quick_wins": quick,
                "appendix": {"file": name, "finding_ids": sorted(sel["by_finding"]), "counts": c,
                             "line": L["appendix_line"].format(file=name, findings=c["findings"], cards=len(todos),
                                                               confirm=c["confirm"], notes=c["notes"],
                                                               appendix=c["appendix_only"], limits=c["own_limits"])}}

    def worst(self, row):
        """A by_page row's worst severity; from its findings when a saved row lacks it."""
        if row.get("worst_severity"):
            return row["worst_severity"]
        found = [self.findings.get(i, {}).get("severity") for i in row.get("finding_ids") or []]
        return next((s for s in SEVERITIES if s in found), None)

    def read_urls(self):
        """İçeriği okunan sayfaların adresleri (Maya'nın kendi taraması + Firecrawl)."""
        urls = {p.get("url") for p in (self.r.get("crawl") or {}).get("pages") or []
                if isinstance(p.get("status"), int) and 200 <= p["status"] < 300 and p.get("content_checks_eligible") is not False}
        urls |= {p.get("url") for p in (self.r.get("firecrawl") or {}).get("pages") or [] if p.get("outcome") == "read"}
        return {u for u in urls if u}

    def perf_action(self, lab, i):
        short = {"Largest Contentful Paint": "LCP", "Total Blocking Time": "TBT", "Cumulative Layout Shift": "CLS"}
        metrics = " / ".join(short.get(m, m) for m in lab["slow"]) or "LCP"
        return {"n": i + 1, "ref": f"diagnostic:{lab['check_id']}", "owner": self.L["owners"]["developer"], "effort": self.L["efforts"]["M"],
                "title": FIXED["perf_action"][self.lang].format(metrics=metrics)}

    @staticmethod
    def _without_empty_columns(sample):
        """An evidence table never prints a column that is empty ("—") in every row (DECISIONS 300 (7), 305)."""
        keep = [j for j in range(len(sample["columns"])) if j == 0 or any(row[j] not in ("—", "", None) for row in sample["rows"])]
        sample["columns"] = [sample["columns"][j] for j in keep]
        sample["rows"] = [[row[j] for j in keep] for row in sample["rows"]]
        return sample

    def evidence_sample(self, f):
        L, ev = self.L, f.get("evidence") or {}
        rows = None
        for value in ev.values():
            if isinstance(value, list) and value and isinstance(value[0], dict) and "url" in value[0]:
                rows = value
                break
        total = (f.get("scope") or {}).get("count") or 0
        if rows and rows[0].get("attempts"):
            item = rows[0]
            attempts = [a for a in item["attempts"] if isinstance(a, dict)][:EV_ROWS]
            out = []
            for k, a in enumerate(attempts):
                d = parse_dt(a.get("requested_at"))
                label = L["ev_first"] if k == 0 else L["ev_repeat"] if len(attempts) == 2 else L["ev_attempt"].format(n=k + 1)
                body = a.get("body_bytes")
                out.append([label, d.strftime("%H:%M:%S") if d else "—", str(a.get("status") or "—"),
                            L["ev_bytes"].format(n=body) if body is not None else "—"])
                self.fact(a.get("status"), body)
            method = attempts[0].get("method") or "GET"
            self.fact(total)
            return {"finding_id": f["id"], "kind": "attempts",
                    "caption": f"{path_of(item.get('url'))} · {method} · {date_long(attempts[0].get('requested_at'), L)} / UTC",
                    "columns": [L["ev_request"], L["ev_time"], L["ev_http"], L["ev_body"]], "rows": out,
                    "alert_col": 3 if any(str(a.get("body_bytes")) == "0" for a in attempts) else None,
                    "note": L["ev_note_sample"].format(total=total)}
        # The engine's structured evidence first (DECISIONS 271): the measured value and its limit ("885 KB", "500 KB").
        facts = [x for x in self._w("facts")(self.rule_of(f), ev) or [] if isinstance(x, dict)]
        if facts:
            out = []
            for x in facts[:EV_ROWS]:
                out.append([path_of(x.get("url")) if x.get("url") else "—", str(x.get("element") or "—"),
                            str(x.get("observed") or "—"), str(x.get("expected") or "—")])
                self.fact(x.get("observed"), x.get("expected"))
            return self._without_empty_columns(
                {"finding_id": f["id"], "kind": "rows", "caption": f.get("id"),
                 "columns": [L["ev_url"], L["ev_element"], L["ev_measured"], L["ev_limit"]], "rows": out, "alert_col": None,
                 "note": L["ev_note_urls"].format(n=len(out))})
        if rows:
            out = []
            for item in rows[:EV_ROWS]:
                out.append([path_of(item.get("url")), str(item.get("status") or "—"),
                            L["ev_bytes"].format(n=item["body_bytes"]) if item.get("body_bytes") is not None else (item.get("element") or "—")])
                self.fact(item.get("status"))
            return self._without_empty_columns(
                {"finding_id": f["id"], "kind": "rows", "caption": f.get("id"),
                 "columns": [L["ev_url"], L["ev_http"], L["ev_result"]], "rows": out, "alert_col": None,
                 "note": L["ev_note_urls"].format(n=len(out))})
        urls = ((f.get("scope") or {}).get("urls")) or []
        if urls:
            return {"finding_id": f["id"], "kind": "urls", "caption": f.get("id"), "columns": [L["ev_url"]],
                    "rows": [[path_of(u)] for u in urls[:EV_ROWS]], "alert_col": None, "note": L["ev_note_urls"].format(n=min(EV_ROWS, len(urls)))}
        return None

    def search(self):
        L, lang = self.L, self.lang
        c = self.dfs.get("DFS-4")
        data = ((c or {}).get("evidence") or {}).get("data") or {}
        table = data.get("table") or {}
        cols = table.get("columns") or []
        if not c or c.get("status") not in ("observed", "partial") or not table.get("rows"):
            return {"state": "missing", "note": L["search_none"]}
        rel_i = cols.index("Relevance") if "Relevance" in cols else None
        rows = [r for r in table["rows"] if isinstance(r[1], int)]
        rows.sort(key=lambda r: -r[1])
        rows = rows[:3]
        top = max((r[1] for r in rows), default=1) or 1
        out, ranking_page = [], None
        for r in rows:
            rel = r[rel_i] if rel_i is not None else None
            out.append({"query": r[0], "volume": fmt_int(r[1], lang), "share": round(r[1] / top, 3), "rank": r[2],
                        "label": L.get(f"rel_{rel}", "") if rel else ""})
            self.fact(r[1], r[2])
            if rel != "branded" and ranking_page is None and len(r) > 3:
                ranking_page = path_of(r[3])
        return {"state": "ok", "rows": out, "ranking_page": ranking_page,
                "source": L["search_source"].format(date=date_long((c.get("evidence") or {}).get("data_from"), L))}


def lab_value(v, lang):
    """Lighthouse displayValue ('6.1 s', '870 ms') -> TR: '6,1 sn', '870 ms'."""
    if not v or lang != "tr":
        return v
    v = re.sub(r"(\d)\.(\d)", r"\1,\2", str(v))
    return re.sub(r"\s?s$", " sn", v) if not v.endswith("ms") else v


def _short(text):
    return re.sub(r"\s+", " ", text or "").strip()


def first_upper(text, lang):
    """Sentence case for a sentence that starts lower case. Turkish i/ı are İ/I ("İlk", not "Ilk"); a sentence that
    starts with a tag or attribute name ("og:site_name …", "<h1> …") keeps it as written (Carpex w13)."""
    if not text or re.match(r"[a-z][\w-]*:|<", text):
        return text
    head = {"i": "İ", "ı": "I"}.get(text[0], text[0].upper()) if lang == "tr" else text[0].upper()
    return head + text[1:]


def _strip_count(text):
    t = re.sub(r"^\s*\d[\d,.]*\s*", "", text or "").strip()
    return t[:1].upper() + t[1:] if t else t


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report")
    ap.add_argument("--lang", required=True, choices=["tr", "en"])
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--rev", default=None, help="Revizyon etiketi, ör. r3")
    ap.add_argument("--audit-id", default=None)
    ap.add_argument("--source", default=None, help="Alt bilgideki veri kaynağı, ör. \"Maya Audit PDF (r3)\". Verilmezse report.json yazar.")
    ap.add_argument("--reanalysis", action="store_true",
                    help="Kayıtlı kanıtın çevrimdışı yeniden analizi (yeni tarama yapılmadı). Yalnız gerçekten öyleyse ver.")
    ap.add_argument("--maya-src", default=None, help="maya_audit_web içeren Maya Audit kaynak klasörü (Türkçe başlıklar için)")
    ap.add_argument("--review", default=None, help="İnceleme dosyası (review.json); verilmezse report.json'un yanındaki")
    ap.add_argument("--no-reassess", action="store_true",
                    help="Raporu olduğu gibi kullan; güncel motorla yeniden değerlendirme yapma (DECISIONS 308)")
    ap.add_argument("--by", default=None, help="--confirm/--reject: kim kontrol etti")
    ap.add_argument("--seen", default=None, help="--confirm/--reject: tarayıcıda ne görüldü")
    ap.add_argument("--note", default=None, help="--confirm: kartta görünecek ek not (isteğe bağlı)")
    ap.add_argument("--confirm", action="append", default=[],
                    help="Sahibin elle teyit ettiği bulgu (kural kimliği ya da bulgu kimliği, ör. str12.language); "
                         "'Teyit edin' listesinden kartlara geçer (DECISIONS 300)")
    ap.add_argument("--reject", action="append", default=[],
                    help="Sahibin elle kontrolde yanlış bulduğu bulgu; PDF'te gösterilmez, ekte 'reddedildi' olarak kalır")
    a = ap.parse_args()
    rp = Path(a.report).resolve()
    if a.confirm or a.reject:
        if not a.by or not a.seen:
            sys.exit("HATA: --confirm/--reject için --by (kim) ve --seen (ne görüldü) gerekir.")
        try:
            record_checks(rp, a.review, a.confirm, a.reject, by=a.by, seen=a.seen, note=a.note, maya_src=a.maya_src,
                          reassess=not a.no_reassess)
        except BuildError as exc:
            sys.exit(f"HATA: {exc}")
    try:
        data, notes = build_from_files(rp, a.lang, rev=a.rev, audit_id=a.audit_id, source=a.source, reanalysis=a.reanalysis,
                                       maya_src=a.maya_src, review=a.review, reassess=not a.no_reassess)
    except BuildError as exc:
        sys.exit(f"HATA: {exc}")
    for line in notes:
        print(line)
    Path(a.out).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    raw = json.dumps({k: v for k, v in data.items() if not k.startswith("_")}, ensure_ascii=False)
    print(f"data.json yazıldı: {a.out}")
    print(f"  dil: {a.lang} · bulgu tablosu: {len(data['findings'])} · aksiyon: {len(data['actions'])} · "
          f"motor çevirisi: {'var' if data['_engine_wording'] else 'yok'}")
    print(f"  model alanı: {len(data['_slots'])} · doldurulacak (⟪YAZ⟫): {raw.count('⟪YAZ')}")


class BuildError(Exception):
    """No draft can be built (an old schema, no engine); the message says why, in Turkish as the skill prints it."""


def _review_file(rp, review):
    from maya_audit import manual_review  # type: ignore
    return Path(review) if review else manual_review.path_for(rp)


def record_checks(rp, review, confirm, reject, *, by, seen, note=None, maya_src=None, reassess=True):
    """--confirm / --reject: the owner's manual checks into the audit's review file (DECISIONS 301 (1))."""
    if load_final(maya_src) is None:
        raise BuildError("Maya Audit motoru (maya_audit.final) bulunamadı; --maya-src ile verin.")
    from maya_audit import manual_review  # type: ignore
    from maya_audit.release_gate import findings_of  # type: ignore
    review_path = _review_file(Path(rp), review)
    # The findings the team report is built from (DECISIONS 308): a rule the current engine added can be checked too.
    from maya_audit_web.team_report import current as current_engine
    known = findings_of(load(current_engine.current(Path(rp)).report_path if reassess else rp))
    for result, keys in (("confirmed", confirm or []), ("rejected", reject or [])):
        for key in keys:
            ids = [key] if key in known else [i for i, f in known.items() if f.get("rule_id") == key]
            if not ids:
                raise BuildError(f"raporda {key} kimlikli ya da kurallı bulgu yok.")
            for fid in ids:
                manual_review.record(review_path, manual_review.entry(fid, result, by=by, seen=seen, note=note,
                                                                      rule_id=known[fid].get("rule_id")))
    print(f"İnceleme dosyası güncellendi: {review_path}")


def build_from_files(report_path, lang, *, rev=None, audit_id=None, source=None, reanalysis=False, maya_src=None,
                     review=None, affected_path=None, reassess=True):
    """report.json (and the files beside it) -> data.json as a dict, plus the lines the CLI prints. The one path of the
    skill's build step and of the web app's team report (DECISIONS 307). Raises BuildError when nothing can be built.

    A saved report is first re-evaluated with the current engine (DECISIONS 308, `current.current`): the report is built
    from that derived copy; the source is never written. The review file stays the source's (`artifacts/review.json`),
    so a check made in the web app's "Teyit edin" counts in the skill's report too. `reassess=False` builds the file
    as it is."""
    src = Path(report_path).resolve()
    notes = []
    review_path = _review_file(src, review)
    if not audit_id and src.parent.name == "artifacts":
        audit_id = src.parent.parent.name  # ~/.maya-audit/web/audits/<id>/artifacts/report.json
    if affected_path is None:
        affected_path = next((p for p in (src.with_name(src.stem + ".affected-urls.json"), src.parent / "affected-urls.json")
                              if p.exists()), None)
    rp = src
    reassess_failed = None
    if reassess:
        if load_final(maya_src) is None:
            raise BuildError("Maya Audit motoru (maya_audit.final) bulunamadı; --maya-src ile verin.")
        from maya_audit_web.team_report import current as current_engine
        try:
            cur = current_engine.current(src, affected_path)
        except Exception as exc:  # noqa: BLE001 - a report the current engine cannot re-read is used as written, said so
            cur = None
            reassess_failed = f"{type(exc).__name__}: {exc}"[:200]
            notes.append(f"  UYARI: güncel motorla yeniden değerlendirilemedi ({reassess_failed}); rapor kaydedildiği hâliyle kullanıldı")
        if cur is not None:
            rp, affected_path = cur.report_path, cur.affected_path
            if cur.reassessed:
                notes.append(f"  Güncel motorla yeniden değerlendirildi: {rp} ({len(cur.changes)} değişiklik; kaynak değişmedi)")
    report = load(rp)
    if reassess_failed:
        report.setdefault("generation", {})["_reassess_failed"] = reassess_failed
    side = src.parent / "dataforseo.json"
    if not report.get("dataforseo") and side.exists():
        report["dataforseo"] = load(side)  # Maya web uygulaması paneli ayrıca bu dosyaya da yazar
        notes.append("  DataForSEO verisi yandaki dataforseo.json dosyasından alındı")
    if not str(report.get("schema_version") or "").startswith("1."):
        raise BuildError(f"report.json şeması 1.x değil ({report.get('schema_version') or report.get('report_version')}). "
                         "Eski bir rapor; Maya Audit'in güncel sürümüyle yeniden üretilmeli.")
    labels = load(REFS / "etiketler.json")[lang]
    catalog = load(REFS / "sahip_efor.json")
    w = Wording(lang, maya_src)
    # CLI: <report>.affected-urls.json (named after the report); web app: affected-urls.json in its artifacts folder.
    affected = load(affected_path) if affected_path else {}
    if affected:
        # Read from beside report.json; it must belong to the same saved audit.
        notes.append(f"affected-urls.json okundu: {affected_path}")
    # DECISIONS 283: the client PDF is built from the same final result as every other output (maya_audit.final) and
    # carries its release-gate decision; without the engine nothing is built.
    final = load_final(maya_src)
    if final is None:
        raise BuildError("Maya Audit motoru (maya_audit.final) bulunamadı; --maya-src ile verin. "
                         "Ortak son sonuç ve yayın kapısı olmadan taslak üretilmez.")
    sealed = final.from_report(report, affected or None)
    try:
        from maya_audit import client_selection, manual_review  # type: ignore
    except ImportError:
        raise BuildError("Maya Audit motorunda client_selection yok (DECISIONS 300); güncel motoru --maya-src ile verin.") from None
    confirmations = manual_review.confirmations(manual_review.load(review_path))
    selection = client_selection.select(sealed.report, affected or None, confirmations)
    data = Builder(sealed.report, lang, labels, catalog, w, rev, audit_id, reanalysis, affected,
                   cards=sealed.cards, selection=selection).build()
    data["_confirmations"] = confirmations
    # The engine that re-evaluated this saved audit (DECISIONS 308), None when the report was used as written.
    data["_engine"] = ((report.get("generation") or {}).get("analysis") or {}).get("engine")
    data["_reassess_failed"] = reassess_failed
    data["_review_path"] = str(review_path) if review_path.exists() else None
    data["_digest"] = sealed.digest
    data["_gate_decision"] = sealed.decision
    data["meta"]["source"] = source
    # Where the release gate reads the report and the engine from (DECISIONS 278); never printed in the report.
    data["_report_path"] = str(rp)
    data["_affected_path"] = str(affected_path) if affected_path else None
    data["_maya_src"] = str(Path(maya_src).resolve()) if maya_src else None
    # DECISIONS 307: the skill may polish the text fields; severities, counts and order are locked.
    from maya_audit_web.team_report.validate_data import locked_digest
    data["_locked"] = locked_digest(data)
    return data, notes


if __name__ == "__main__":
    main()
