"""The review fix log (DECISIONS 363): every issue the SEO team noted, how it was fixed, and whether the newest saved audit
of its domain still shows it.

`fix_log.json` holds the items (written from the review files and DECISIONS; brands are only where the note was made),
each with a `check` the rebuilt audit is tested by (`CHECKS`; `tools/fix_log.py` does the rebuilding). The statuses of
the last run are kept in `fix_log_status.json`, so every Ek can show the "Düzeltme kaydı" sheet (`ek_sheet`): the items
that are rules for every audit, newest first, at most 50, with no brand, file or person named.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ITEMS_FILE = Path(__file__).with_name("fix_log.json")
STATUS_FILE = Path(__file__).with_name("fix_log_status.json")
FIXED, OPEN, PARTLY, CRAWL = "Düzeltildi", "Hâlâ var", "Kısmen", "Yeni tarama gerekli"
EK_ROWS = 50
SEVERE = ("S1", "S2", "S3", "S4")

BRANDS = {"enpara": {"name": "Enpara", "domain": "enpara.com"},
          "atasun": {"name": "Atasun Optik", "domain": "atasunoptik.com.tr"},
          "naturesgarden": {"name": "Nature's Garden", "domain": "naturesgarden.net"},
          "isbank": {"name": "İş Bankası", "domain": "isbank.com.tr"},
          "ticimax": {"name": "Ticimax", "domain": "ticimax.com"},
          "carpex": {"name": "Carpex", "domain": "carpexonline.com"},
          "mmi": {"name": "MMI", "domain": "mmihomedelivery.ae"}}


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(ITEMS_FILE.read_text(encoding="utf-8"))


def items() -> list[dict]:
    out = []
    for n, item in enumerate(_data()["items"], 1):
        out.append({**item, "no": n})
    return out


# ---------------------------------------------------------------- checks on a rebuilt audit

def _findings(ctx: dict) -> list[dict]:
    return [f for c in ctx["report"].get("checks") or [] for f in c.get("findings") or []]


def _rule(f: dict) -> str:
    return f.get("rule_id") or ""


def _cards_with(ctx: dict, rules) -> list[dict]:
    ids = {f["id"] for f in _findings(ctx) if _rule(f) in rules}
    return [t for t in ctx["cards"] if set(t.get("finding_ids") or []) & ids]


def _cell_rows(ctx: dict, sheet: str, column: str | None):
    rows = ctx["book"].get(sheet) or []
    if not rows:
        return None
    head = rows[0]
    cols = [head.index(column)] if column and column in head else range(len(head)) if not column else []
    return [[str(r[i]) for i in cols if i < len(r) and r[i] is not None] for r in rows[1:]]


def _text(card: dict, field: str) -> str:
    v = card.get(field)
    return "\n".join(v) if isinstance(v, list) else str(v or "")


def check_one(kind: str, arg, ctx: dict) -> bool:
    if kind == "no_card":  # no card carries a finding of these rules
        return not _cards_with(ctx, set(arg))
    if kind == "no_problem":  # no finding of these rules above Info
        return not any(_rule(f) in arg and f.get("severity") in SEVERE for f in _findings(ctx))
    if kind == "has_finding":  # the audit has a finding of one of these rules
        return any(_rule(f) in arg for f in _findings(ctx))
    if kind == "card_text":  # every card of these rules says this (and, with "need", there is one)
        cards = _cards_with(ctx, set(arg["rules"]))
        if not cards:
            return not arg.get("need")
        return all(re.search(arg["regex"], _text(c, arg["field"]), re.I) for c in cards)
    if kind == "no_text":  # no card's title or steps says this
        return not any(re.search(arg, _text(c, f), re.I) for c in ctx["cards"] for f in ("title", "steps"))
    if kind == "title_text":  # a card whose title matches has this in a field (no such card: passes)
        cards = [c for c in ctx["cards"] if re.search(arg["title"], c.get("title") or "", re.I)]
        return all(re.search(arg["regex"], _text(c, arg["field"]), re.I) for c in cards) if cards else not arg.get("need")
    if kind == "sheet_has":  # some cell of the sheet (column) matches
        rows = _cell_rows(ctx, arg["sheet"], arg.get("column"))
        return bool(rows) and any(re.search(arg["regex"], cell, re.I) for r in rows for cell in r)
    if kind == "sheet_not":  # no cell of the sheet (column) matches; no sheet passes
        rows = _cell_rows(ctx, arg["sheet"], arg.get("column")) or []
        return not any(re.search(arg["regex"], cell, re.I) for r in rows for cell in r)
    if kind == "severity_info":  # every finding of these rules is Info (or there is none)
        return all(f.get("severity") == "Info" for f in _findings(ctx) if _rule(f) in arg)
    if kind == "gate":
        return ctx.get("gate") == arg
    if kind == "has_observation":  # the check carries this observation
        return any(o.get("metric") == arg["metric"] for c in ctx["report"].get("checks") or [] if c.get("check_id") == arg["check"]
                   for o in c.get("observations") or [])
    if kind == "row_not":  # rows whose key column matches never have this in the column
        rows = ctx["book"].get(arg["sheet"]) or []
        if not rows:
            return True
        head = rows[0]
        k, c = head.index(arg["key"]), head.index(arg["column"])
        return not any(re.search(arg["match"], str(r[k] or "")) and re.search(arg["regex"], str(r[c] or ""), re.I)
                       for r in rows[1:] if len(r) > max(k, c))
    raise ValueError(f"unknown check {kind}")


def status_of(item: dict, ctx: dict | None, tests: dict[str, bool] | None = None) -> tuple[str, str]:
    """(Durum, how it was checked). A test the item names must pass (`tests`: {file: passed}); a check on the rebuilt
    audit must hold."""
    check = item.get("check") or {}
    if check.get("crawl"):
        return CRAWL, check.get("why") or "yeni tarama gerekli"
    test_ok = None if not check.get("test") else bool((tests or {}).get(check["test"]))
    conds = [(k, v) for k, v in check.items() if k not in ("test", "why", "crawl")]
    results = ([check_one(k, v, ctx) for k, v in conds] if ctx is not None else []) + ([test_ok] if test_ok is not None else [])
    if ctx is None and conds:
        return OPEN, "kayıtlı denetim yok"
    if not results:
        return OPEN, "doğrulanamadı"
    how = ("denetim yeniden kuruldu" if conds else "") + (", " if conds and test_ok is not None else "") + \
          ("test geçti" if test_ok else "test geçmedi" if test_ok is not None else "")
    passed = sum(1 for x in results if x)
    return (FIXED if passed == len(results) else PARTLY if passed else OPEN), how


def evaluate(all_items: list[dict], built: dict[str, dict], commits: dict[int, tuple[str, str]], today: str,
             tests: dict[str, bool] | None = None) -> list[dict]:
    rows = []
    for item in all_items:
        ctx = built.get(item.get("brand_key"))
        durum, how = status_of(item, ctx, tests)
        nos = item.get("decisions") or []
        found = [commits[n] for n in nos if n in commits]
        commit, date = (found[-1] if found else ("—", today))  # fixed in a change not yet committed: today
        audit = (ctx or {}).get("audit") or {}
        kontrol = (f"{audit['id'][:8]} ({audit['finished_at'][:10]}); {how}" if audit else how) + f"; {today}"
        rows.append({"no": item["no"], "kaynak": item["kaynak"], "marka": BRANDS.get(item.get("brand_key"), {}).get("name", "Tümü"),
                     "sorun": item["sorun"], "durum": durum, "nasil": item["nasil"], "tarih": date, "commit": commit,
                     "decisions": ", ".join(str(n) for n in nos) or "—", "kontrol": kontrol, "genel": item.get("genel"),
                     "scope": item.get("scope", "all")})
    return rows


# ---------------------------------------------------------------- outputs

COLUMNS = ["No", "Kaynak", "Marka", "Sorun", "Durum", "Nasıl düzeltildi", "Tarih", "Commit", "DECISIONS no", "Kontrol"]
HOWTO = [
    "Bu dosya SEO ekibinin (Efsa, İlginay) Maya raporları için yazdığı notları ve her birinin durumunu tek listede toplar.",
    "Kaynak: notun geldiği inceleme dosyası ya da DECISIONS kaydı ve notu yazan kişi. Aynı not birkaç dosyada geçtiyse bir kez yazılır ve en yeni dosya adı verilir.",
    "Marka: notun yazıldığı denetim. Düzeltmeler markaya özel değildir; aynı kural her denetimde çalışır.",
    "Durum: Düzeltildi (markanın en yeni kayıtlı denetimi yeniden kurulup sorunun gittiği görüldü); Hâlâ var; Kısmen (bir kısmı düzeldi); Yeni tarama gerekli (kayıtlı veri sorunun gittiğini gösteremiyor, site yeniden taranmalı).",
    "Nasıl düzeltildi: değişikliğin tek cümlelik özeti. Tarih ve Commit: düzeltmenin kaydedildiği gün ve değişikliğin kimliği; DECISIONS no: kararın ayrıntılı yazıldığı madde.",
    "Kontrol: doğrulamada kullanılan denetim (kimliğinin ilk 8 karakteri ve tarihi), nasıl doğrulandığı ve doğrulama günü. Yeni tarama yapılmadı; kayıtlı denetimler güncel kurallarla yeniden kuruldu.",
    "Ekip yalnız indirilen raporlar üzerinde değil, sitenin en yeni denetimi üzerinde kontrol edilmiştir: eski bir dosyadaki not, aynı alan adının en yeni denetiminde doğrulandı.",
]


def workbook(rows: list[dict]) -> bytes:
    from . import xlsx
    body = [[r["no"], r["kaynak"], r["marka"], r["sorun"], r["durum"], r["nasil"], r["tarih"], r["commit"], r["decisions"],
             r["kontrol"]] for r in rows]
    return xlsx.workbook([
        {"name": "Nasıl okunur", "header": ["Nasıl okunur"], "rows": [[x] for x in HOWTO], "widths": [140], "frozen": False,
         "filter": False},
        {"name": "Düzeltme kaydı", "header": COLUMNS, "rows": body, "widths": [6, 40, 14, 60, 18, 70, 12, 10, 12, 40]}])


def save_status(rows: list[dict]) -> None:
    keep = [{k: r[k] for k in ("no", "durum", "tarih", "commit", "decisions")} for r in rows]
    STATUS_FILE.write_text(json.dumps({"rows": keep}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


EK_COLUMNS = {"tr": ["Tarih", "Sorun", "Durum", "Nasıl düzeltildi", "DECISIONS no"],
              "en": ["Date", "Issue", "Status", "How it was fixed", "DECISIONS no"]}
EK_NAME = {"tr": "Düzeltme kaydı", "en": "Fix log"}


def ek_sheet(lang: str = "tr") -> dict | None:
    """DECISIONS 363: the Ek's "Düzeltme kaydı": the items that are rules for every audit, worded without a brand, file
    or person (`genel`), with the status of the last check, newest first, at most EK_ROWS. None when nothing is logged."""
    try:
        status = {r["no"]: r for r in json.loads(STATUS_FILE.read_text(encoding="utf-8"))["rows"]}
    except (OSError, ValueError, KeyError):
        status = {}
    rows = []
    for item in items():
        st = status.get(item["no"])
        if item.get("scope", "all") != "all" or not item.get("genel") or st is None:
            continue
        rows.append([st.get("tarih") or "", item["genel"], st.get("durum") or "", item["nasil"], st.get("decisions") or ""])
    if not rows:
        return None
    rows.sort(key=lambda r: (r[0] or "", r[4]), reverse=True)
    return {"name": EK_NAME.get(lang, EK_NAME["tr"]), "header": EK_COLUMNS.get(lang, EK_COLUMNS["tr"]), "rows": rows[:EK_ROWS],
            "widths": [12, 70, 16, 80, 12]}
