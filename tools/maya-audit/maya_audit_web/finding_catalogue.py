"""The finding catalogue (DECISIONS 353): every finding, card and checklist item the engine can produce, in one XLSX
the SEO team rewrites, and the import that puts their new Turkish texts back into the data files.

Export (`export`): one row per text the reader sees, with the rule's family, severity seen, priority cap, issue type,
the Turkish card texts (title, why it matters, what to do and its steps, how to verify), the engine's finding sentence
with its placeholders, the evidence fields, the business profiles and platforms it applies to, and how many of the
saved audits on this computer triggered it (read only) with one real sentence. Variants (platform steps, region steps)
are rows of their own. The columns "Yeni başlık", "Yeni açıklama", "Yeni öneri", "Yeni bulgu cümlesi" and "Not" are
empty for the team.

Import (`read_edits`, `plan`, `apply`): only a row whose "Yeni …" cell holds text changes anything; every other row is
left as it is. Each new text is checked before anything is written: the same placeholders as the old text ({n},
{where}, "{n:sayfa|sayfa}", [[...]]), balanced brackets, no digits where the old text had none (numbers come from the
report), the field's length limit, the step count a conditional step needs. A row that fails is refused and listed; the
rest are written. The result is a diff report (old -> new per file and field).

Where the texts live (all data files, no text in code): `team_report/texts/tr.json` (card fields per rule, merge group
and Note topic), `maya_audit/rule_actions.json` (the approved card title and steps, which win over the library),
`maya_audit/merge_group_texts.json` (merged cards' title, finding and fix), `locales/findings/tr.json` (the engine's
finding sentences in Turkish), `maya_audit/checklist_items.json` (the 165-item checklist).
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "texts": ROOT / "maya_audit_web" / "team_report" / "texts" / "tr.json",
    "actions": ROOT / "maya_audit" / "rule_actions.json",
    "groups": ROOT / "maya_audit" / "merge_group_texts.json",
    "findings": ROOT / "maya_audit_web" / "locales" / "findings" / "tr.json",
    "checklist": ROOT / "maya_audit" / "checklist_items.json",
}
SHEET = "Bulgular"
NEW = ("Yeni başlık", "Yeni açıklama", "Yeni öneri", "Yeni bulgu cümlesi", "Not")
HEADER = ["Anahtar", "Tür", "Kural ID", "Aile", "Aile adı", "Önem (kayıtlı denetimlerde)", "Öncelik", "Sorun türü",
          "Başlık", "Bulgu", "Neden önemli", "Ne yapılmalı", "Doğrulama", "Bulgu cümlesi (motor, TR)",
          "Motor cümlesi (EN)", "Yer tutucular", "Kanıt alanları", "Profiller", "Platformlar", "Metin çeşitleri",
          "Kaç denetimde", "Örnek cümle (gerçek)", "Kaynak dosyalar", *NEW]
WIDTHS = [26, 16, 26, 8, 26, 16, 14, 12, 40, 34, 50, 60, 40, 44, 44, 18, 30, 26, 16, 14, 10, 50, 30, 30, 40, 50, 40, 30]
TITLE_LIMIT, STEP_LIMIT, STEP_MIN, STEP_MAX = 80, 75, 2, 4
_NAME = re.compile(r"\{(\w+)(?::[^{}]*)?\}")
_SILENT = re.compile(r"\[(\w+):[^\[\]|]*\|[^\[\]]*\]")
_OPTIONAL = re.compile(r"\[\[.*?\]\]", re.S)


# ---------------------------------------------------------------- reading the sources

def _load(name: str) -> dict:
    return json.loads(FILES[name].read_text(encoding="utf-8"))


def _write(name: str, data: dict) -> None:
    FILES[name].write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def placeholders(text: str | None) -> list[str]:
    """The placeholder names a text uses, in any form ({n}, {n:sayfa|sayfa}, [n:its|their], [[...]] marks)."""
    if not text:
        return []
    names = set(_NAME.findall(text)) | {m.group(1) for m in _SILENT.finditer(text)}
    return sorted(names) + (["[[…]]"] if "[[" in text else [])


def _check_of_rules() -> dict[str, str]:
    data = json.loads((ROOT / "maya_audit" / "rule_ids.json").read_text(encoding="utf-8"))["rules"]
    return {rule: check for check, rows in data.items() for rule, _ in rows}


def _profiles_of(rule: str, check: str) -> str:
    """Business profiles a rule is a sector check for (the team's sector method); every site otherwise."""
    method = json.loads((ROOT / "maya_audit" / "sector_method.json").read_text(encoding="utf-8"))

    def hit(refs):
        return any(r == check or rule == r or rule.startswith(r + ".") for r in refs or [])
    core = any(hit(row.get("rules")) for row in method.get("core") or [])
    sectors = sorted({row.get("sector") for row in method.get("sec") or [] if hit(row.get("rules"))} - {None})
    parts = ["Tüm siteler" + (" (ortak kontrol)" if core else "")]
    if sectors:
        parts.append("Sektör kontrolü: " + ", ".join(sectors))
    return "; ".join(parts)


@dataclass
class Seen:
    """What the saved audits on this computer show about each rule (read only)."""
    audits: int = 0
    by_rule: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    severity: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    example: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    check_titles: dict[str, str] = field(default_factory=dict)


def saved_reports(home: Path | None) -> Iterable[tuple[str, Path]]:
    """(audit id, report path) of every saved audit under a web home: the current-engine copy when there is one."""
    folder = Path(home) / "audits" if home else None
    if not folder or not folder.is_dir():
        return
    for audit in sorted(p for p in folder.iterdir() if p.is_dir()):
        for candidate in (audit / "current-engine" / "report.json", audit / "artifacts" / "report.json"):
            if candidate.is_file():
                yield audit.name, candidate
                break


def read_saved(home: Path | None) -> Seen:
    """Counts per rule over the saved audits; files are only read. A report that cannot be read is skipped."""
    from maya_audit_web import wording
    seen = Seen()
    for audit_id, path in saved_reports(home):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        seen.audits += 1
        for check in (report.get("checks") or []) + (report.get("answer_engine_panel") or []):
            cid = check.get("check_id") or ""
            if cid and check.get("title") and cid not in seen.check_titles:
                seen.check_titles[cid] = wording.label(check["title"], "tr", cid)[0] or check["title"]
            for f in check.get("findings") or []:
                rule = f.get("rule_id") or next(iter(wording.title_key(cid, f.get("title") or "")), None)
                if not rule:
                    continue
                seen.by_rule[rule].add(audit_id)
                sev = f.get("severity")
                seen.severity[rule][getattr(sev, "value", sev) or "?"] += 1
                seen.evidence[rule].update(k for k in (f.get("evidence") or {}) if k not in ("judgment", "severity_assessment"))
                if rule not in seen.example and f.get("title"):
                    seen.example[rule] = wording.title(cid, f["title"], "tr")[0]
    return seen


# ---------------------------------------------------------------- the rows

def _what_to_do(explanation: str | None, steps: list[str] | None) -> str:
    lines = [explanation or ""] if explanation else []
    return "\n".join(lines + [f"- {s}" for s in steps or []])


def rows(home: Path | None = None, seen: Seen | None = None) -> list[dict]:
    """Every catalogue row as {column: value}. `home`: a web home whose saved audits are counted (read only)."""
    return _rows(home, seen)


def _issue_types() -> tuple[dict, dict]:
    data = json.loads((ROOT / "maya_audit" / "issue_types.json").read_text(encoding="utf-8"))
    return data["rules"], data["labels"]["tr"]


def _rows(home: Path | None, seen: Seen | None) -> list[dict]:
    from maya_audit import client_selection, priority_levels
    from maya_audit_web import wording
    from maya_audit_web.team_report import texts as T
    seen = seen or read_saved(home)
    lib, actions, groups = _load("texts"), _load("actions")["actions"], _load("groups")["groups"]
    finding_tr = _load("findings")["titles"]
    kinds, kind_words = _issue_types()
    checks = _check_of_rules()
    english_frames = {key: frame for rows_ in wording._TITLES.values() for key, frame, _ in rows_}
    rule_ids = sorted(set(checks) | set(lib["rules"]) | set(actions))
    out: list[dict] = []

    def caps(rule: str) -> str:
        cap = next((c for r, c in priority_levels.RULE_CAPS.items() if rule == r or rule.startswith(r + ".")), None)
        return f"en çok {cap}" if cap else "puana göre (P0–P3)"

    for rule in rule_ids:
        check = checks.get(rule, "")
        entry = T.rule(rule, "tr")
        own = lib["rules"].get(rule) or {}
        act = actions.get(rule) or {}
        sources = []
        sources.append("başlık: rule_actions.json" if act.get("tr") else "başlık: texts/tr.json")
        approved = (act.get("steps") or {}).get("tr") or []
        steps_from = "rule_actions.json" if len(approved) >= 2 and not any(act.get("step_when") or []) else (
            "rule_actions.json (koşullu adımlar)" if act.get("step_when") else "texts/tr.json")
        sources.append(f"adımlar: {steps_from}")
        sources.append("neden/açıklama/doğrulama: texts/tr.json" if own else "neden/açıklama/doğrulama: genel metin (kurala özel metin yok)")
        if rule in finding_tr:
            sources.append("bulgu cümlesi: locales/findings/tr.json")
        steps_shown = approved if steps_from.startswith("rule_actions") else entry.get("steps") or []
        platforms = sorted(set((act.get("steps_by_platform") or {})) | set((own.get("steps_by_platform") or {})))
        regions = sorted((act.get("region_steps") or {}))
        sev = seen.severity.get(rule) or Counter()
        ev = [k for k, _ in (seen.evidence.get(rule) or Counter()).most_common(8)]
        n_audits = len(seen.by_rule.get(rule) or ())
        base = {
            "Anahtar": f"rule:{rule}", "Tür": "Kural", "Kural ID": rule, "Aile": check,
            "Aile adı": seen.check_titles.get(check, ""),
            "Önem (kayıtlı denetimlerde)": ", ".join(f"{k}×{v}" for k, v in sorted(sev.items())) or "—",
            "Öncelik": caps(rule), "Sorun türü": kind_words.get(kinds.get(rule, ""), "—"),
            "Başlık": entry.get("title") or "", "Bulgu": entry.get("finding") or "", "Neden önemli": entry.get("why") or "",
            "Ne yapılmalı": _what_to_do(entry.get("explanation"), steps_shown), "Doğrulama": entry.get("verify") or "",
            "Bulgu cümlesi (motor, TR)": finding_tr.get(rule, ""), "Motor cümlesi (EN)": english_frames.get(rule, ""),
            "Yer tutucular": ", ".join(placeholders(finding_tr.get(rule)) or placeholders(english_frames.get(rule))) or "—",
            "Kanıt alanları": ", ".join(ev) or "—", "Profiller": _profiles_of(rule, check),
            "Platformlar": ", ".join(platforms) + " (ayrı satırlarda)" if platforms else "Tümü",
            "Metin çeşitleri": 1 + len(platforms) + len(regions),
            "Kaç denetimde": f"{n_audits}/{seen.audits}", "Örnek cümle (gerçek)": seen.example.get(rule, "—"),
            "Kaynak dosyalar": "; ".join(sources),
        }
        out.append(base)
        for platform in platforms:
            steps = ((act.get("steps_by_platform") or {}).get(platform) or {}).get("tr") or (own.get("steps_by_platform") or {}).get(platform) or []
            out.append({**_blank(base), "Anahtar": f"rule:{rule}|platform:{platform}", "Tür": f"Kural · {platform} adımları",
                        "Kural ID": rule, "Aile": check, "Platformlar": platform, "Ne yapılmalı": _what_to_do(None, steps),
                        "Kaynak dosyalar": "adımlar: " + ("rule_actions.json" if (act.get("steps_by_platform") or {}).get(platform) else "texts/tr.json"),
                        "Kaç denetimde": base["Kaç denetimde"]})
        for region in regions:
            out.append({**_blank(base), "Anahtar": f"rule:{rule}|region:{region}", "Tür": f"Kural · bölge adımı ({region})",
                        "Kural ID": rule, "Aile": check, "Ne yapılmalı": (act["region_steps"][region] or {}).get("tr") or "",
                        "Kaynak dosyalar": "adım: rule_actions.json", "Kaç denetimde": base["Kaç denetimde"]})
    for gid, g in groups.items():
        gl = (lib.get("groups") or {}).get(gid) or {}
        merged = client_selection.MERGE_BY_ID.get(gid) or {}
        members = list(merged.get("rules") or [])
        n_audits = len(set().union(*[seen.by_rule.get(r) or set() for r in members])) if members else 0
        out.append({**_blank({}), "Anahtar": f"group:{gid}", "Tür": "Birleşik kart", "Kural ID": ", ".join(members),
                    "Başlık": g["title"]["tr"], "Bulgu": g["finding"]["tr"], "Neden önemli": gl.get("why") or "",
                    "Ne yapılmalı": _what_to_do(gl.get("explanation") or g["fix"]["tr"], gl.get("steps")),
                    "Doğrulama": gl.get("verify") or "", "Profiller": "Tüm siteler", "Platformlar": "Tümü",
                    "Metin çeşitleri": 1, "Kaç denetimde": f"{n_audits}/{seen.audits}",
                    "Kaynak dosyalar": "başlık/bulgu: merge_group_texts.json; neden/açıklama/adımlar/doğrulama: texts/tr.json"})
    for topic, note in (lib.get("notes") or {}).items():
        if topic.startswith("_"):
            continue
        out.append({**_blank({}), "Anahtar": f"note:{topic}", "Tür": "Not kartı konusu", "Kural ID": topic,
                    "Başlık": note.get("summary") or "", "Ne yapılmalı": note.get("step") or "", "Profiller": "Tüm siteler",
                    "Platformlar": "Tümü", "Metin çeşitleri": 1, "Kaynak dosyalar": "texts/tr.json (notes)"})
    generic = lib["generic"]
    out.append({**_blank({}), "Anahtar": "generic", "Tür": "Genel (kurala özel metni olmayan bulgu)", "Kural ID": "—",
                "Başlık": generic["title"], "Bulgu": generic["finding"], "Neden önemli": generic["why"],
                "Ne yapılmalı": _what_to_do(generic["explanation"], generic["steps"]), "Doğrulama": generic["verify"],
                "Profiller": "Tüm siteler", "Platformlar": "Tümü", "Metin çeşitleri": 1, "Kaynak dosyalar": "texts/tr.json (generic)"})
    for item in _load("checklist")["items"]:
        refs = list(item.get("rules") or []) + list(item.get("checks") or [])
        hits = set()
        for rule, ids in seen.by_rule.items():
            check = checks.get(rule, "")
            if any(r == check or rule == r or rule.startswith(r + ".") for r in refs):
                hits |= ids
        out.append({**_blank({}), "Anahtar": f"checklist:{item['id']}", "Tür": "Kontrol listesi maddesi",
                    "Kural ID": ", ".join(refs) or "—", "Aile": item.get("group") or "", "Öncelik": item.get("priority") or "",
                    "Başlık": item.get("item") or "", "Kanıt alanları": item.get("maya_note") or "",
                    "Profiller": item.get("applies_to") or "", "Platformlar": "Tümü", "Metin çeşitleri": 1,
                    "Kaç denetimde": f"{len(hits)}/{seen.audits}" if refs else "elle kontrol",
                    "Kaynak dosyalar": "checklist_items.json"})
    return out


def _blank(_base: dict) -> dict:
    return {h: "" for h in HEADER}


# ---------------------------------------------------------------- the XLSX

HOWTO = [
    "Bu dosya Maya Audit'in üretebildiği her bulguyu, kartı ve kontrol listesi maddesini listeler (DECISIONS 353).",
    "Yalnız «Yeni …» sütunlarını doldurun; boş bıraktığınız satır değişmez. «Anahtar» sütununu değiştirmeyin.",
    "Yeni başlık: kartın başlığı (yapılacak iş). Yeni açıklama: «Neden önemli» cümlesi.",
    "Yeni öneri: ilk satır «Ne yapılmalı» cümlesi; «- » ile başlayan her satır bir adım (2–4 adım, her biri en çok 75 karakter). "
    "Yalnız «- » satırları yazarsanız yalnız adımlar değişir.",
    "Yeni bulgu cümlesi: motorun Türkçe bulgu cümlesi. «Yer tutucular» sütunundaki adların hepsi aynen kalmalı "
    "({n}, {where}, {n:sayfa|sayfa} …); sayılar oradan gelir, metne sayı yazmayın.",
    "Metinlerde rakam yazmayın: her sayı rapordan gelir. Platforma özgü adımlar kendi satırlarında.",
    "Not: SEO ekibinin notu; içe aktarmada metne yazılmaz, fark raporunda listelenir.",
    "Geri yükleme: python scripts/finding_catalogue.py import <bu dosya> (önce --dry-run ile fark raporu).",
]


def export(path: Path, home: Path | None = None) -> dict:
    """Write the catalogue XLSX; returns counts {rows, rules, kinds, audits}."""
    from maya_audit import xlsx, text_gate
    seen = read_saved(home)
    made = rows(home, seen)
    body = [[r.get(h, "") for h in HEADER] for r in made]
    phrases = [[p["text"], p["lang"], "Evet" if p["block"] else "Hayır", p.get("why") or "", p.get("instead") or ""]
               for p in text_gate.phrases()]
    sheets = [
        {"name": "Nasıl kullanılır", "header": ["Nasıl kullanılır"], "rows": [[x] for x in HOWTO], "widths": [140], "filter": False},
        {"name": SHEET, "header": HEADER, "rows": body, "widths": WIDTHS},
        {"name": "Yasaklı ifadeler", "header": ["İfade", "Dil", "İndirmeyi taslak yapar", "Neden", "Yerine"], "rows": phrases,
         "widths": [40, 8, 14, 30, 40]},
    ]
    Path(path).write_bytes(xlsx.workbook(sheets))
    kinds = Counter("Kural çeşidi" if r["Tür"].startswith("Kural · ") else r["Tür"] for r in made)
    return {"rows": len(made), "rules": kinds.get("Kural", 0), "kinds": dict(kinds),
            "audits": seen.audits, "triggered": sum(1 for r in made if r["Tür"] == "Kural" and not r["Kaç denetimde"].startswith("0/"))}


# ---------------------------------------------------------------- the import

class CatalogueError(ValueError):
    pass


def read_edits(path: Path) -> list[dict]:
    """The rows of an edited catalogue that hold at least one "Yeni …" text: [{key, title, why, advice, sentence, note}]."""
    from maya_audit import xlsx
    book = xlsx.read_any(Path(path).read_bytes())
    sheet = book.get(SHEET)
    if not sheet:
        raise CatalogueError(f"'{SHEET}' sayfası yok: bu dosya bulgu kataloğu değil")
    head = [str(h or "").strip() for h in sheet[0]]
    if "Anahtar" not in head or any(n not in head for n in NEW):
        raise CatalogueError("'Anahtar' ya da 'Yeni …' sütunları eksik: katalog sütunlarını değiştirmeyin")
    at = {h: head.index(h) for h in head if h}
    out = []
    for row in sheet[1:]:
        cell = lambda name: (str(row[at[name]]).strip() if at[name] < len(row) and row[at[name]] is not None else "")  # noqa: E731
        edit = {"key": cell("Anahtar"), "title": cell("Yeni başlık"), "why": cell("Yeni açıklama"),
                "advice": cell("Yeni öneri"), "sentence": cell("Yeni bulgu cümlesi"), "note": cell("Not")}
        if edit["key"] and any(edit[k] for k in ("title", "why", "advice", "sentence", "note")):
            out.append(edit)
    return out


@dataclass
class Change:
    key: str
    file: str
    field: str
    old: Any
    new: Any


def _split_advice(text: str) -> tuple[str | None, list[str] | None]:
    lines = [line.rstrip() for line in text.replace("\r", "").split("\n") if line.strip()]
    steps = [re.sub(r"^\s*[-•–]\s*", "", line).strip() for line in lines if re.match(r"^\s*[-•–]\s", line)]
    first = [line.strip() for line in lines if not re.match(r"^\s*[-•–]\s", line)]
    return (" ".join(first) or None), (steps or None)


def _same_placeholders(old: str | None, new: str) -> str | None:
    if placeholders(old) != placeholders(new):
        return (f"yer tutucular değişmiş: eski {', '.join(placeholders(old)) or 'yok'}, "
                f"yeni {', '.join(placeholders(new)) or 'yok'}")
    for a, b in (("{", "}"), ("[[", "]]"), ("(", ")"), ("«", "»")):
        if new.count(a) != new.count(b):
            return f"'{a}' ve '{b}' sayısı eşit değil"
    return None


def _no_new_digits(old: str | None, new: str) -> str | None:
    plain = lambda s: re.sub(r"\{[^{}]*\}|<[^<>]*>|\b[Hh][1-6]\b|\bUTF-8\b|\b[1-5]xx\b", "", s or "")  # noqa: E731
    if re.search(r"\d", plain(new)) and not re.search(r"\d", plain(old)):
        return "metinde rakam var: sayılar rapordan gelir, metne yazılmaz"
    return None


def _sentence_fill(new: str, old: str) -> str | None:
    """A finding sentence must fill: every placeholder given a sample value, nothing left in braces."""
    from maya_audit_web import wording
    values = {name: 2 for name in placeholders(old) if name != "[[…]]"}
    try:
        text = wording.fill(new, values)
    except (KeyError, IndexError, ValueError) as exc:
        return f"cümle doldurulamıyor: {exc}"
    if re.search(r"\{[^{}]*\}", text):
        return "doldurulduktan sonra süslü parantez kalıyor"
    return None


def plan(edits: list[dict]) -> tuple[list[Change], list[dict], list[dict]]:
    """(the changes to write, the refused rows with why, the notes). Nothing is written."""
    lib, act_file, groups_file = _load("texts"), _load("actions"), _load("groups")
    actions = act_file["actions"]
    finding_tr = _load("findings")["titles"]
    checklist = {i["id"]: i for i in _load("checklist")["items"]}
    changes: list[Change] = []
    refused: list[dict] = []
    notes = [{"key": e["key"], "note": e["note"]} for e in edits if e.get("note")]
    for e in edits:
        key = e["key"]
        mine: list[Change] = []
        why_not: list[str] = []

        def text_field(file: str, path: str, old: str | None, new: str, limit: int | None, digits: bool = True):
            if not new:
                return
            problem = _same_placeholders(old, new) or (digits and _no_new_digits(old, new)) or None
            if not problem and limit and len(new) > limit:
                problem = f"{len(new)} karakter; en çok {limit}"
            if problem:
                why_not.append(f"{path}: {problem}")
            elif new != old:
                mine.append(Change(key, file, path, old, new))

        def steps_field(file: str, path: str, old: list[str], new: list[str] | None, fixed_count: int | None = None):
            if not new:
                return
            if fixed_count is not None and len(new) != fixed_count:
                why_not.append(f"{path}: {fixed_count} adım olmalı (koşullu adımlar sırayla eşleşir), {len(new)} yazılmış")
                return
            if not STEP_MIN <= len(new) <= STEP_MAX and fixed_count is None:
                why_not.append(f"{path}: {len(new)} adım; {STEP_MIN}–{STEP_MAX} olmalı")
                return
            for n, line in enumerate(new):
                problem = (_same_placeholders(old[n] if n < len(old) else "", line) or
                           _no_new_digits(" ".join(old), line))
                if not problem and len(line) > STEP_LIMIT:
                    problem = f"{n + 1}. adım {len(line)} karakter; en çok {STEP_LIMIT}"
                if problem:
                    why_not.append(f"{path}[{n + 1}]: {problem}")
                    return
            if new != old:
                mine.append(Change(key, file, path, old, new))

        explanation, steps = _split_advice(e.get("advice") or "")
        if key.startswith("rule:"):
            rule, _, variant = key[5:].partition("|")
            own = lib["rules"].get(rule)
            act = actions.get(rule) or {}
            if own is None and not act and rule not in finding_tr:
                refused.append({"key": key, "why": "bilinmeyen kural"})
                continue
            if variant.startswith("platform:"):
                platform = variant.split(":", 1)[1]
                if (act.get("steps_by_platform") or {}).get(platform):
                    steps_field("actions", f"actions.{rule}.steps_by_platform.{platform}.tr",
                                act["steps_by_platform"][platform]["tr"], steps)
                elif (own or {}).get("steps_by_platform", {}).get(platform):
                    steps_field("texts", f"rules.{rule}.steps_by_platform.{platform}", own["steps_by_platform"][platform], steps)
                if e.get("title") or e.get("why") or e.get("sentence") or explanation:
                    why_not.append("platform satırında yalnız adımlar (- ile başlayan satırlar) değişir")
            elif variant.startswith("region:"):
                region = variant.split(":", 1)[1]
                old = ((act.get("region_steps") or {}).get(region) or {}).get("tr")
                text_field("actions", f"actions.{rule}.region_steps.{region}.tr", old, " ".join(filter(None, [explanation] + (steps or []))), STEP_LIMIT)
            else:
                if e.get("title"):
                    if act.get("tr"):
                        text_field("actions", f"actions.{rule}.tr", act["tr"], e["title"], TITLE_LIMIT)
                    else:
                        text_field("texts", f"rules.{rule}.title", (own or {}).get("title"), e["title"], TITLE_LIMIT)
                if e.get("why"):
                    text_field("texts", f"rules.{rule}.why", (own or {}).get("why"), e["why"], 170)
                if explanation:
                    text_field("texts", f"rules.{rule}.explanation", (own or {}).get("explanation"), explanation, 150)
                if steps:
                    approved = (act.get("steps") or {}).get("tr") or []
                    if act.get("step_when"):
                        steps_field("actions", f"actions.{rule}.steps.tr", approved, steps, fixed_count=len(approved))
                    elif len(approved) >= 2:
                        steps_field("actions", f"actions.{rule}.steps.tr", approved, steps)
                    else:
                        steps_field("texts", f"rules.{rule}.steps", (own or {}).get("steps") or [], steps)
                if e.get("sentence"):
                    old = finding_tr.get(rule)
                    if old is None:
                        why_not.append("bu kuralın Türkçe bulgu cümlesi yok (cümle başka bir kalıptan geliyor)")
                    else:
                        text_field("findings", f"titles.{rule}", old, e["sentence"], None, digits=False)
                        problem = _sentence_fill(e["sentence"], old) if not why_not else None
                        if problem:
                            why_not.append(f"titles.{rule}: {problem}")
        elif key.startswith("group:"):
            gid = key[6:]
            g = groups_file["groups"].get(gid)
            if g is None:
                refused.append({"key": key, "why": "bilinmeyen birleşik kart"})
                continue
            gl = (lib.get("groups") or {}).get(gid) or {}
            if e.get("title"):
                text_field("groups", f"groups.{gid}.title.tr", g["title"]["tr"], e["title"], TITLE_LIMIT)
            if e.get("sentence"):
                text_field("groups", f"groups.{gid}.finding.tr", g["finding"]["tr"], e["sentence"], 70)
            if e.get("why"):
                text_field("texts", f"groups.{gid}.why", gl.get("why"), e["why"], 170)
            if explanation:
                text_field("texts", f"groups.{gid}.explanation", gl.get("explanation"), explanation, 150)
            if steps:
                steps_field("texts", f"groups.{gid}.steps", gl.get("steps") or [], steps)
        elif key.startswith("note:"):
            topic = key[5:]
            note = (lib.get("notes") or {}).get(topic)
            if note is None:
                refused.append({"key": key, "why": "bilinmeyen Not konusu"})
                continue
            if e.get("title"):
                text_field("texts", f"notes.{topic}.summary", note.get("summary"), e["title"], 40)
            line = " ".join(filter(None, [explanation] + (steps or [])))
            if line:
                text_field("texts", f"notes.{topic}.step", note.get("step"), line, 100)
        elif key == "generic":
            g = lib["generic"]
            if e.get("title"):
                text_field("texts", "generic.title", g["title"], e["title"], TITLE_LIMIT)
            if e.get("why"):
                text_field("texts", "generic.why", g["why"], e["why"], 170)
            if explanation:
                text_field("texts", "generic.explanation", g["explanation"], explanation, 150)
            if steps:
                steps_field("texts", "generic.steps", g["steps"], steps)
        elif key.startswith("checklist:"):
            item = checklist.get(key[10:])
            if item is None:
                refused.append({"key": key, "why": "bilinmeyen kontrol listesi maddesi"})
                continue
            if e.get("title"):
                text_field("checklist", f"items.{item['id']}.item", item.get("item"), e["title"], 120)
            if e.get("why") or explanation or steps or e.get("sentence"):
                why_not.append("kontrol listesi maddesinde yalnız başlık değişir")
        else:
            refused.append({"key": key, "why": "Anahtar tanınmadı (sütunu değiştirmeyin)"})
            continue
        if why_not:
            refused.append({"key": key, "why": "; ".join(why_not)})
        else:
            changes.extend(mine)
    return changes, refused, notes


def _set(data: dict, path: str, value: Any, file: str) -> None:
    """Set a dotted path whose keys may hold dots themselves (rule ids: "str7.alt_missing"): at each level the longest
    run of parts that is an existing key is taken. The checklist's items are a list found by id."""
    parts = path.split(".")
    if file == "checklist":
        item = next(i for i in data["items"] if i["id"] == parts[1])
        item[".".join(parts[2:])] = value
        return
    node, at = data, 0
    while True:
        rest = len(parts) - at
        for size in range(rest, 0, -1):
            key = ".".join(parts[at:at + size])
            if key in node and at + size < len(parts) and isinstance(node[key], dict):
                node, at = node[key], at + size
                break
        else:
            node[".".join(parts[at:])] = value
            return


def apply(changes: list[Change]) -> list[str]:
    """Write the changes, one read and one write per file; returns the files written."""
    by_file: dict[str, list[Change]] = defaultdict(list)
    for c in changes:
        by_file[c.file].append(c)
    written = []
    for file, items in by_file.items():
        data = _load(file)
        for c in items:
            _set(data, c.field, c.new, file)
        _write(file, data)
        written.append(str(FILES[file].relative_to(ROOT)))
    return written


def diff_report(changes: list[Change], refused: list[dict], notes: list[dict], applied: bool) -> str:
    def show(v):
        return "\n".join(f"    {x}" for x in v) if isinstance(v, list) else f"    {v}"
    lines = [f"# Bulgu kataloğu içe aktarma — {'yazıldı' if applied else 'deneme (hiçbir şey yazılmadı)'}", "",
             f"Değişen alan: {len(changes)} · Reddedilen satır: {len(refused)} · Not: {len(notes)}", ""]
    for c in changes:
        lines += [f"## {c.key} · {FILES[c.file].relative_to(ROOT)} · {c.field}", "- eski:", show(c.old), "+ yeni:", show(c.new), ""]
    if refused:
        lines += ["## Reddedilen satırlar (dosyalara yazılmadı)", ""]
        lines += [f"- {r['key']}: {r['why']}" for r in refused] + [""]
    if notes:
        lines += ["## SEO ekibinin notları (metne yazılmaz)", ""]
        lines += [f"- {n['key']}: {n['note']}" for n in notes] + [""]
    return "\n".join(lines)
