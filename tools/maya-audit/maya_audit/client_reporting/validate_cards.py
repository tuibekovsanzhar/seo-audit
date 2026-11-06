"""cards.json'u render öncesi denetler. Hata varsa çıkış kodu 1.

Ayrıca --fix ile güvenli düzeltmeleri yapar: canlıda doğrulanmamış Kritik/Yüksek
(launch_gated) kartları ve 10'dan fazla ana kartı eke taşır.

Kullanım:
  python validate_cards.py cards.json [--fix]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

from .reliability import fully_verified, safety_errors, strings, score_label

BANNED = ["şizofreni", "kettles", "teapots", "brand.example", "lorem", "ipsum"]
BANNED_WORD = re.compile(r"(?<![\w.])Brand(?![\w.])")
INTERNAL_ID = re.compile(r"\b[a-zçğıöşü]+_[a-zçğıöşü_]+\b")
CHECK_CODE = re.compile(r"\b(ACC|IDX|RND|STR|PRF|ANS|INT|TSEO|DFS)-\d+\b")
SEVERITIES = {"Kritik", "Yüksek", "Orta", "Düşük", "Bilgi"}
STOP = set("ve ile için bir bu da de ne mi mu mü mı ya veya en çok daha gibi olan olarak sayfa sayfası | – - : · ve".split())


def norm_words(t):
    # Türkçe büyük/küçük harf: I -> ı, İ -> i; karşılaştırmada ı ve i aynı sayılır
    t = unicodedata.normalize("NFC", (t or "").replace("İ", "i").replace("I", "ı").lower().replace("i̇", "i"))
    t = t.replace("ı", "i").replace("â", "a").replace("î", "i").replace("û", "u")
    return [w for w in re.findall(r"[a-zçğöşü0-9]+", t) if len(w) >= 2 and w not in STOP]


def visible_texts(card):
    yield "title", card.get("title")
    yield "why", (card.get("why") or {}).get("text")
    for i, s in enumerate(card.get("steps") or []):
        yield f"steps[{i}]", s
    yield "verify", card.get("verify")
    wtw = card.get("what_to_write") or {}
    yield "what_to_write.text", wtw.get("text")
    yield "what_to_write.decide", wtw.get("decide")


def lg_ids(c):
    """Yalnızca LG-xx kimlikleri 'doğrulanmamış kontrol' sayılır; serbest notlar sayılmaz."""
    return [x for x in ((c.get("maya") or {}).get("launch_gated") or []) if re.match(r"^LG-\d+$", str(x))]


# müşteriye hitap: "…yapmalısınız / …etmelisiniz", or (DECISIONS 316: one Turkish instruction form across the reports)
# the polite imperative "…doğrulayın / …kaldırmayın" the engine's fix translations now use.
MALISINIZ = re.compile(r"m[ae]l[ıi]s[ıi]n[ıi]z|\w{2,}(?<!iç)(?:y?[ıiuü]n)(?=[\s.;,:!)]|$)", re.I)


ENGLISH = re.compile(r"\b(the|of|and|page\(s\)|pages|was|were|not assessed|could not|requires|none|missing|returns?)\b", re.I)


def _validate(d, fix=False):
    errs, warns, moved = [], [], []

    if fix:
        keep = []
        for c in d.get("cards", []):
            if lg_ids(c) and not fully_verified(c):
                moved.append(c.get("id")); d["appendix_cards"].insert(0, c)
            else:
                keep.append(c)
        while len(keep) > 10:
            c = keep.pop(); moved.append(c.get("id")); d["appendix_cards"].insert(0, c)
        d["cards"] = keep
        main_ids = {c.get("id") for c in keep}
        for c in keep:  # eke taşınan karta bağımlılık kalmasın
            if c.get("depends_on") and c["depends_on"] not in main_ids:
                print(f"depends_on temizlendi: {c.get('id')} → {c['depends_on']} (ana bölümde değil)")
                c["depends_on"] = None

    main_ids = {c.get("id") for c in d.get("cards", [])}
    if len((d.get("summary") or {}).get("bullets") or []) > 4:
        errs.append("summary.bullets 4'ten fazla")
    if not 3 <= len(d.get("kpis") or []) <= 5:
        errs.append(f"kpis sayısı {len(d.get('kpis') or [])}; 3–5 olmalı")

    if len(d.get("cards", [])) > 10:
        errs.append(f"Ana kart sayısı {len(d['cards'])} > 10")
    for k in ("meta", "coverage", "kpis", "summary"):
        if not d.get(k):
            errs.append(f"Üst düzey alan eksik: {k}")
    if not (d.get("summary") or {}).get("one_read"):
        errs.append("summary.one_read boş")
    if not (d.get("coverage") or {}).get("line"):
        errs.append("coverage.line boş")

    # çevrilmemiş alan ve kart dışı görünür metinler
    if '"_needs_tr": true' in json.dumps(d, ensure_ascii=False):
        errs.append("Çevrilmemiş alan var (_needs_tr: true): not_measured / changes_since_last metinlerini Türkçeye çevirip işareti kaldırın")
    english = ENGLISH
    outer = [("summary.one_read", (d.get("summary") or {}).get("one_read"))]
    outer += [(f"summary.bullets[{i}]", b) for i, b in enumerate((d.get("summary") or {}).get("bullets") or [])]
    for i, k in enumerate(d.get("kpis") or []):
        outer += [(f"kpis[{i}].{f}", k.get(f)) for f in ("label", "note")]
    for sec in ("manual_checks", "not_measured"):
        for i, x in enumerate(d.get(sec) or []):
            outer += [(f"{sec}[{i}].{f}", v) for f, v in x.items() if isinstance(v, str)]
    for sec, items in ((d.get("changes_since_last") or {}).items()):
        if isinstance(items, list):
            outer += [(f"changes.{sec}[{i}]", x.get("title")) for i, x in enumerate(items)]
    for field, txt in outer:
        if not txt:
            continue
        if any(b in txt.lower() for b in BANNED) or BANNED_WORD.search(txt):
            errs.append(f"{field}: yasaklı yer tutucu")
        if english.search(re.sub(r"`[^`]*`|\S*[/.]\S*", " ", txt)):
            errs.append(f"{field}: İngilizce kalmış görünüyor: {txt[:70]}")

    for where, cards, strict in (("cards", d.get("cards", []), True), ("appendix_cards", d.get("appendix_cards", []), False)):
        for c in cards:
            cid = c.get("id")
            p = f"{where}/{cid}"
            if not c.get("title"):
                errs.append(f"{p}: title boş (Türkçe başlık yazılmalı)")
            if c.get("severity") not in SEVERITIES:
                errs.append(f"{p}: severity '{c.get('severity')}' geçersiz")
            if not strict and not c.get("steps"):
                errs.append(f"{p}: ek kartta en az bir ilk adım olmalı")
            hitap = list(enumerate(c.get("steps") or [])) if strict else list(enumerate((c.get("steps") or [])[:1]))
            for i, st in hitap:
                if st and not MALISINIZ.search(st):
                    errs.append(f"{p}.steps[{i}]: '-ın / -malısınız' biçiminde yazılmalı: {st[:60]}")
            if strict and c.get("verify") and not MALISINIZ.search(c["verify"]):
                errs.append(f"{p}.verify: '-ın / -malısınız' biçiminde yazılmalı: {c['verify'][:60]}")
            if strict:
                if lg_ids(c) and not fully_verified(c):
                    errs.append(f"{p}: doğrulanmamış kontrol ana bölümde; canlıda doğrulayın ya da --fix ile eke taşıyın")
                for req in ("owner", "effort"):
                    if not c.get(req):
                        errs.append(f"{p}: {req} boş")
                if c.get("depends_on") and c["depends_on"] not in main_ids:
                    errs.append(f"{p}: depends_on '{c['depends_on']}' ana bölümde bir kart değil")
                if not c.get("steps"):
                    errs.append(f"{p}: steps boş")
                if len(c.get("steps") or []) > 5:
                    errs.append(f"{p}: 5'ten fazla adım")
                if not c.get("verify"):
                    errs.append(f"{p}: verify boş (düzeltmenin nasıl doğrulanacağı)")
                if not (c.get("why") or {}).get("text"):
                    errs.append(f"{p}: why.text boş")
                ex = (c.get("where") or {}).get("examples") or []
                if not ex and (c.get("where") or {}).get("group") != "site geneli":
                    warns.append(f"{p}: örnek URL yok")
                w = c.get("what_to_write") or {}
                for it in w.get("items") or []:
                    fld, prop = (it.get("field") or "").lower(), it.get("proposed") or ""
                    if "title" in fld and len(prop) > 60:
                        errs.append(f"{p}: önerilen title 60 karakterden uzun")
                    if "description" in fld and not 70 <= len(prop) <= 160:
                        errs.append(f"{p}: önerilen description 70–160 karakter olmalı")
                if not (w.get("items") or w.get("text") or w.get("code") or (w.get("decide") or "").startswith("Karar vermelisiniz:")):
                    errs.append(f"{p}: what_to_write kanıtlı öneri veya Karar vermelisiniz: içermeli")
            for field, txt in visible_texts(c):
                if not txt:
                    continue
                low = txt.lower()
                for b in BANNED:
                    if b in low:
                        errs.append(f"{p}.{field}: yasaklı yer tutucu '{b}'")
                if BANNED_WORD.search(txt):
                    errs.append(f"{p}.{field}: yer tutucu 'Brand'")
                if field in ("title", "why", "verify") or field.startswith("steps"):
                    no_code = re.sub(r"`[^`]*`", " ", txt)
                    no_url = re.sub(r"\S*[/.]\S*", " ", no_code)
                    if INTERNAL_ID.search(no_url):
                        errs.append(f"{p}.{field}: iç kod görünüyor: {INTERNAL_ID.search(no_url).group(0)}")
                    if CHECK_CODE.search(no_code):
                        errs.append(f"{p}.{field}: kontrol kodu görünür metinde: {CHECK_CODE.search(no_code).group(0)}")
                    if ENGLISH.search(no_url):
                        errs.append(f"{p}.{field}: İngilizce kalmış görünüyor: {txt[:60]}")

    if fix and d.get("score") is not None and all("maya" in c for c in d.get("cards", [])):
        from . import from_maya_report as F
        cfg = json.loads((Path(__file__).resolve().parent / "references" / "onem_kurallari.json").read_text(encoding="utf-8"))["score"]
        sc, per = F.score(d["cards"] + d.get("appendix_cards", []), d["coverage"], cfg)
        d["score"].update({"value": sc, "lost_by_check": {k: round(v, 1) for k, v in per.items()}})
        for k in d.get("kpis", []):
            if k.get("label", "").startswith("Genel puan"):
                k["value"] = score_label(sc, d["coverage"])
        print(f"Puan yeniden hesaplandı: {sc} (doğrulanmamış bulgular hariç)")

    errs.extend(safety_errors(d, norm_words))
    for path, text in strings(d):
        if any(b in text.lower() for b in BANNED) or BANNED_WORD.search(text):
            errs.append(f"{path}: yasaklı yer tutucu")
        if ('what_to_write' in path or path.endswith('.title')) and CHECK_CODE.search(text):
            errs.append(f"{path}: görünür kontrol kodu")
    return errs, warns, moved


def validate(d, fix=False):
    """No mutation unless an explicit --fix caller requests it; renderer always uses fix=False."""
    if not isinstance(d, dict):
        return ["Girdi JSON nesnesi olmalı"], [], []
    try:
        return _validate(d, fix=fix)
    except (TypeError, KeyError, AttributeError, ValueError) as exc:
        return [f"Geçersiz alan yapısı: {exc}; kart sözleşmesini kontrol edin"], [], []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cards')
    ap.add_argument('--fix', action='store_true')
    a = ap.parse_args()
    try:
        d = json.loads(Path(a.cards).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        sys.exit(f"HATA: JSON okunamadı: {exc}")
    errs, warns, moved = validate(d, fix=a.fix)
    if a.fix:
        Path(a.cards).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
        if moved: print('Eke taşındı:', ', '.join(map(str,moved)))
    for w in warns: print('UYARI:', w)
    for e in errs: print('HATA:', e)
    print(f'Sonuç: {len(errs)} hata, {len(warns)} uyarı')
    sys.exit(1 if errs else 0)


if __name__ == '__main__':
    main()
