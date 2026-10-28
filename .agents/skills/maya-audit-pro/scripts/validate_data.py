"""data.json denetimi: render'dan önce koşar, hata varsa 1 ile çıkar.

Kullanım:
  python validate_data.py data.json

Denetlenenler (yalnız modelin yazdığı / `_slots` alanları ve görünen metinler):
  - doldurulmamış ⟪YAZ⟫ işareti,
  - alan uzunluğu (kutuya sığması için `_slots[].max`),
  - metinde rapora dayanmayan sayı (`_facts` dışında; ≤5 küçük sayılar uyarı),
  - dil karışması (TR raporda İngilizce kelime, EN raporda Türkçe harf),
  - ham veri sızıntısı ([{' , None, True/False) ve yasaklı yer tutucular,
  - tablo sınırları (≤5 bulgu, ≤5 aksiyon, ≤3 öncelik) ve KPI tutarlılığı,
  - Maya Audit'in yayın kapısı (maya_audit/release_gate.py, DECISIONS 278): kart ile bulgu, adres, yeniden sınama,
    kartlar arası atıf, sabit başlık ve koşullu adım. Kapı çalıştırılamazsa denetim geçmez ve PDF basılmaz.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

EN_WORDS = re.compile(r"\b(the|and|with|of|to|is|are|this|that|from|for|not|page|pages|was|were|should)\b", re.I)
TR_CHARS = re.compile(r"[ğüşıöçĞÜŞİÖÇ]")
RAW = re.compile(r"\[\{'|\{'|\bNone\b|\bTrue\b|\bFalse\b|\\n")
BANNED = re.compile(r"brand\.example|/pricing\b|Kettles|lorem ipsum|TODO|TBD|\bXXX\b", re.I)
NUM = re.compile(r"\d+(?:[.,]\d+)*")


def norm(n: str) -> str:
    """'40,500' / '40.500' -> '40500'; '5.2' kalır."""
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", n):
        return re.sub(r"[.,]", "", n)
    return n.replace(",", ".")


def get(d, path):
    cur = d
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        if part.startswith("["):
            idx = int(part[1:-1])
            if not isinstance(cur, list) or idx >= len(cur):
                return None
            cur = cur[idx]
        else:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
    return cur


GATE_MISSING = "Release gate çalıştırılamadığı için PDF üretilmedi."


def load_gate(d: dict):
    """Maya Audit's release gate (maya_audit/release_gate.py, DECISIONS 278). The skill holds no copy of it: the
    engine is found as installed, at `_maya_src` (build_data --maya-src), or in the repository holding this skill."""
    candidates = [d.get("_maya_src"), str(Path(__file__).resolve().parents[4])]
    for where in [None, *candidates]:
        if where and where not in sys.path and (Path(where) / "maya_audit" / "release_gate.py").exists():
            sys.path.insert(0, where)
        try:
            from maya_audit import release_gate  # type: ignore
            return release_gate
        except ImportError:
            continue
    return None


def gate_check(d: dict) -> tuple[dict | None, str | None]:
    """(the gate's record, None) or (None, why it could not run). Run before validation passes and before a PDF."""
    gate = load_gate(d)
    if gate is None:
        return None, f"{GATE_MISSING} Maya Audit motoru bulunamadı (build_data --maya-src ile verin)."
    rp = d.get("_report_path")
    if not rp or not Path(rp).exists():
        return None, f"{GATE_MISSING} data.json'un report.json yolu yok ya da dosya bulunamıyor: {rp!r}."
    report = json.loads(Path(rp).read_text(encoding="utf-8"))
    ap = d.get("_affected_path")
    affected = json.loads(Path(ap).read_text(encoding="utf-8")) if ap and Path(ap).exists() else None
    return gate.run(report, affected, data=d), None


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    lang = d.get("lang")
    errors, warns = [], []
    facts = {norm(f) for f in d.get("_facts") or []}
    record, missing = gate_check(d)
    if missing:
        errors.append(missing)
    gate = load_gate(d)
    every_path = set().union(*[gate.card_paths(t) for t in d.get("todos") or []]) if gate else set()

    visible = json.dumps({k: v for k, v in d.items() if not k.startswith("_")}, ensure_ascii=False)
    if "⟪YAZ" in visible:
        for s in d.get("_slots") or []:
            v = get(d, s["path"])
            if isinstance(v, str) and "⟪YAZ" in v:
                errors.append(f"{s['path']}: doldurulmadı ({s['hint']})")
        if not errors:
            errors.append("⟪YAZ⟫ işareti kaldı (slot listesi dışında)")

    for s in d.get("_slots") or []:
        v = get(d, s["path"])
        if not isinstance(v, str) or "⟪YAZ" in v:
            continue
        p = s["path"]
        if not v.strip():
            errors.append(f"{p}: boş")
            continue
        if s.get("max") and len(v) > s["max"]:
            errors.append(f"{p}: {len(v)} karakter, en fazla {s['max']} (kutuya sığmaz)")
        if s.get("lines"):
            rows = [r for r in v.split("\n") if r.strip()]
            if not 2 <= len(rows) <= s["lines"]:
                errors.append(f"{p}: {len(rows)} adım; 2 ile {s['lines']} arası olmalı (her adım ayrı satırda)")
            for k, r in enumerate(rows, 1):
                if len(r) > 100:
                    errors.append(f"{p}: {k}. adım {len(r)} karakter, en fazla 100")
        if RAW.search(v):
            errors.append(f"{p}: ham veri izi var ({RAW.search(v).group(0)})")
        if BANNED.search(v):
            errors.append(f"{p}: yasaklı yer tutucu ({BANNED.search(v).group(0)})")
        for n in NUM.findall(v):
            if norm(n) in facts:
                continue
            if re.fullmatch(r"[0-5]", n):
                warns.append(f"{p}: '{n}' sayısı rapor verisinde yok (küçük sayı; bilinçliyse sorun değil)")
            else:
                errors.append(f"{p}: '{n}' sayısı report.json verisinde yok — uydurma sayı yazılamaz")
        # DECISIONS 271/278: a card's addresses are the release gate's (RG-3); a summary field may name any card's.
        if gate and not re.match(r"todos\[\d+\]", p):
            for path in gate.text_addresses(v, every_path):
                errors.append(f"{p}: '{path}' adresi raporun adreslerinde ya da kanıtında yok")
        if lang == "tr":
            hits = sorted({w.lower() for w in EN_WORDS.findall(v)})
            if hits:
                errors.append(f"{p}: Türkçe raporda İngilizce kelime: {', '.join(hits)}")
        elif lang == "en" and TR_CHARS.search(v) and not p.startswith("search"):
            warns.append(f"{p}: İngilizce raporda Türkçe harf (marka/sorgu adı değilse düzeltin)")

    if RAW.search(visible.replace("\\n", "")):
        errors.append(f"görünen metinde ham veri izi: {RAW.search(visible).group(0)}")
    if len(d.get("findings") or []) > 5:
        errors.append("bulgu tablosu 5'ten uzun")
    if len(d.get("actions") or []) > 5:
        errors.append("aksiyon tablosu 5'ten uzun")
    if len(d.get("priorities") or []) > 3:
        errors.append("öncelik listesi 3'ten uzun")
    if not d.get("findings"):
        warns.append("bulgu tablosu boş: raporda sorun yok ya da report.json eksik")

    if record:
        for v in record["violations"]:
            line = f"{v['rule']}: {v['message']}"
            (errors if v["hard"] else warns).append(line)
        print("Yayın öncesi özet (müşteri PDF'ine girmez):")
        print(gate.summary_table(record))
        print()
    for w in warns:
        print("UYARI:", w)
    for e in errors:
        print("HATA:", e)
    if errors:
        print(f"\n{len(errors)} hata. Düzeltip yeniden çalıştırın.")
        sys.exit(1)
    print(f"Tamam: {len(d.get('_slots') or [])} alan denetlendi, {len(warns)} uyarı.")


if __name__ == "__main__":
    main()
