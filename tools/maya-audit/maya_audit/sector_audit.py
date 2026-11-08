"""The team's sector audit workbook, filled from an audit (DECISIONS 324).

The team audits with `docs/business-types/Sektor_Bazli_SEO_Audit_Onceligi.xlsm`: five sheets (Metodoloji, Sektör Önceliği,
Ortak SEO Kontrolleri, Sektörel SEO Kontrolleri, Audit Özeti) whose formulas score each check (20 × impact × page
weight × spread × status factor / effort) and count the progress per sector. This module writes the same five sheets
with the same columns, formulas and dropdowns, and fills what the audit established: "Durum", spread, effort, example
address, evidence, action and owner for the 44 common checks and for the audit's own sector, plus three columns of
Maya's at the end (why this Durum, how much Maya covers, the rules). The team can then edit any row and the sheet
recalculates. The formulas are the team's, effort included: effort is left out of Maya's own card labels only
(`priority_levels`), not out of the team's sheet.

"Durum" (agent defaults, the evidence model: missing is never a pass):
- Hatalı: a finding of the check's rules (on that page type, for a sector row) that is an issue-type Blocker, High or
  Medium; Kısmen Uygun: only Low ones, or ones of the "Kontrol edin" / "Fırsat" type. Rejected findings, Maya's own
  limits and Info notes do not count; a finding waiting in "Teyit edin" leaves the row "Kontrol Edilmedi" and says so.
- Uygun: only for a check Maya decides on its own (status A) whose report checks ran, with no finding, on an audit
  that is not low-coverage; a sector row also needs a page of its type among the pages read.
- Uygulanamaz: the report checks it needs were not applicable (hreflang on a one-language site).
- Kontrol Edilmedi: everything else, with the reason (Search Console, a person, not automated yet, page type not found,
  the check did not run, or "the automatic part is clean" for a partly automatic check).
"""
from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Callable

from . import client_selection as cs
from . import xlsx
from .recommendation_catalog import note

NAME = "sector_method.json"
DURUM = ("Kontrol Edilmedi", "Hatalı", "Kısmen Uygun", "Uygun", "Uygulanamaz")
EFFORT = {"S": 1, "M": 3, "L": 4}
OWNERS = {"developer": "Geliştirici", "seo": "SEO", "content": "İçerik"}
STATUS = {"A": "Otomatik", "K": "Kısmen otomatik", "G": "Search Console gerekir", "P": "Kişi gerekir",
          "M-S": "Henüz otomatik değil (küçük iş)", "M-M": "Henüz otomatik değil (orta iş)",
          "M-L": "Henüz otomatik değil (büyük iş)"}
REASON = {
    "G": "Search Console verisi gerekir; Maya bunu bu denetimde ölçmedi.",
    "P": "Kişinin değerlendirmesi gerekir (doğruluk, iş kararı).",
    "M": "Maya bunu henüz otomatik denetlemiyor (Stage 7).",
    "type": "Bu sayfa türü okunan sayfalar arasında bulunamadı (sitede olmadığı anlamına gelmez).",
    "sector": "Bu denetimin işletme türü bu sektör değil.",
    "no_sector": "İşletme türü «Diğer»: sektörel kontroller seçilmedi.",
    "not_run": "İlgili kontrol bu denetimde çalışmadı.",
    "na": "Bu sitede uygulanamaz (ilgili kontrol uygulanamaz buldu).",
    "low": "Düşük kapsam: okunan sayfa az, «Uygun» yazılmadı.",
    "partly": "Otomatik kısım temiz ({covered}); kalan kısım kişi ya da Search Console bekliyor: {missing}.",
    "clean": "Bulgu yok ({covered}).",
    "clean_partial": "Bulgu yok ({covered}); kontrolün kapsamı kısmi.",
    "found": "Maya'nın bulgusu: {rules}.",
    "waiting": "Teyit bekliyor (Önce bunları kontrol edin): {rules}.",
    "tentative": "Tahmini bulgu, teyit edilmedi: {rules}. Ölçülmüş ya da elle teyit edilmiş bir bulgu Durum'u belirler.",
    "checked_pages": "Bulgu yok: {n} sayfada {what} kontrol edildi.",
    "checked_type": "Bulgu yok: «{type}» türünden {n} sayfada {what} kontrol edildi.",
    "checked_host": "Bulgu yok: {n} alan adında {what} kontrol edildi.",
}
EXTRA = ["Maya: Durum nedeni", "Maya kapsamı", "Maya kuralları", "Not"]
PREFILL_NOTE = ["Ön doldurulan değerler (Maya)",
                "Yaygınlık ve Efor her satırda önceden dolduruldu (ölçülen yaygınlık, yoksa 1; kuralın varsayılan eforu, yoksa 3) "
                "ve düzenlenebilir: Durum «Hatalı» ya da «Kısmen Uygun» yapılınca Öncelik Skoru ve Öncelik hemen hesaplanır."]
SEVERE = ("S1", "S2", "S3")


@lru_cache(maxsize=1)
def method() -> dict:
    """The team's rows with Maya's mapping (built by `tools/sector_method_build.py` from the workbook)."""
    return json.loads(resources.files(__package__).joinpath(NAME).read_text(encoding="utf-8"))


def sector_of(profile_id: str | None) -> str | None:
    return next((s["name"] for s in method()["sectors"] if s["profile"] == profile_id), None)


def _matches(f: dict, refs: list[str]) -> bool:
    """DECISIONS 325: a check id ("IDX-4") matches every finding of that check; a rule id matches itself and its sub-ids
    ("acc2.blocks" -> "acc2.blocks.sample"), never another rule that only starts the same ("acc3.noindex_listed")."""
    rid, cid = f.get("rule_id") or "", f.get("check_id") or ""
    return any(r == cid or rid == r or rid.startswith(r + ".") for r in refs)


# DECISIONS 325: a problem that has not happened yet (a certificate still valid): "Hatalı" only at High or Blocker.
FUTURE_RULES = ("idx2.expires",)
HOST_CHECKS = ("ACC-1", "ACC-2", "IDX-2", "IDX-5")  # robots.txt, hosts and certificates, sitemaps: counted in host names


def _host_level(f: dict) -> bool:
    return bool(cs.host_level(f)) or (f.get("check_id") or "") in HOST_CHECKS


def _hosts(urls: list[str]) -> int:
    from urllib.parse import urlsplit
    return len({(urlsplit(u).hostname or "").lower() for u in urls if u} - {""})


def _spread(n: int, total: int) -> int:
    from .priority_levels import spread
    return spread(n, total)


class _Audit:
    """What the rows need from one audit."""

    def __init__(self, report: dict, selection: dict, lists: dict | None, business: str | None,
                 title: Callable | None, words: Callable | None):
        importance, summary = cs.grouping(report, business)
        info = summary.get("business_type") or {}
        self.profile = info.get("id") if isinstance(info, dict) else None
        self.sector = sector_of(self.profile)
        read = {u.rstrip("/") for u in cs.pages_read(report)}
        self.read = read
        self.ptype = {u.rstrip("/"): r.get("business_page_type") for u, r in importance.items()
                      if u and u.rstrip("/") in read and isinstance(r, dict)}
        self.importance = {u.rstrip("/"): r.get("importance") for u, r in importance.items() if u and isinstance(r, dict)}
        self.count: dict[str, int] = {}
        for kind in self.ptype.values():
            self.count[kind] = self.count.get(kind, 0) + 1
        self.checks = {c.get("check_id"): c.get("status") for c in report.get("checks") or []}
        self.low = bool(cs.low_coverage(report))
        self.measures = {u.rstrip("/"): r for u, r in (selection.get("_page_measures") or {}).items()}
        self.lists, self.title, self.words = lists, title, words
        confirmations = selection.get("_confirmations") or {}
        self.items = []
        for g in selection["groups"]:
            if g.get("placement") in ("rejected", "own_limit"):
                continue
            for m in g["members"]:
                sev = cs.severity(m)
                if sev not in cs.PROBLEM:
                    continue
                urls = cs.affected(m, lists)
                # DECISIONS 325: only a measured finding, or one a person confirmed, sets a Durum
                conf = cs.confidence_class(m, confirmations)
                self.items.append({"f": m, "sev": sev, "waiting": g.get("placement") == "confirm", "measured": conf == "measured",
                                   "kind": cs.rule_type(m.get("rule_id")), "urls": urls, "host": _host_level(m),
                                   "read": [u for u in urls if u.rstrip("/") in read]})
        self.hosts = max(_hosts(list(read)), 1)
        self.claims: dict[tuple[str, str], str] = {}  # (finding id, page type) -> the one sector row it marks

    def best_page(self, urls: list[str]) -> str | None:
        return max(urls, key=lambda u: self.importance.get(u.rstrip("/")) or 0) if urls else None

    def top_of_type(self, kind: str) -> str | None:
        pages = [u for u, t in self.ptype.items() if t == kind]
        return max(pages, key=lambda u: self.importance.get(u) or 0) if pages else None

    def name(self, f: dict) -> str:
        plain = self.words(f) if self.words else None
        if plain and plain.get("title"):
            return plain["title"]
        return (self.title(f.get("check_id"), f.get("title") or "") if self.title else None) or f.get("title") or ""

    def fix(self, f: dict) -> str:
        plain = self.words(f) if self.words else None
        return (plain or {}).get("fix") or f.get("how_to_fix") or ""


def _evaluate(a: _Audit, row: dict, kind: str | None) -> dict:
    """Durum and the filled columns of one row, with Yaygınlık and Efor always filled (DECISIONS 326)."""
    return prefill(row, _judge(a, row, kind))


def prefill(row: dict, out: dict) -> dict:
    """DECISIONS 326: every row has Yaygınlık and Efor, so a teammate who changes "Durum" to Hatalı or Kısmen Uygun gets
    a score and a level at once: the measured spread when a finding gives one, else 1; the effort of the row's rules
    (the catalogue's default per check, the largest of them), else 3. Both stay editable."""
    if out.get("spread") is None:
        out["spread"] = 1
    if out.get("effort") is None:
        out["effort"] = default_effort(row)
    return out


@lru_cache(maxsize=1)
def _check_of() -> dict[str, str]:
    """{rule id: check id} from the rule catalogue."""
    rules = json.loads(resources.files(__package__).joinpath("rule_ids.json").read_text(encoding="utf-8"))["rules"]
    return {r[0]: check for check, rows in rules.items() for r in rows}


def default_effort(row: dict) -> int:
    checks = set()
    for ref in row.get("rules") or []:
        if ref[:1].isupper():
            checks.add(ref)
        else:
            checks.update(c for rid, c in _check_of().items() if rid == ref or rid.startswith(ref + "."))
    efforts = [EFFORT.get(note(c, "")["effort"], 3) for c in sorted(checks)]
    return max(efforts) if efforts else 3


def _judge(a: _Audit, row: dict, kind: str | None) -> dict:
    """Durum and the filled columns of one check row (`kind`: the page type of a sector row, None for a common one)."""
    from .page_rows import measured
    st = row["status"]
    rel = []
    for x in a.items:
        if not _matches(x["f"], row["rules"]):
            continue
        if kind is not None:
            urls = [u for u in x["read"] if a.ptype.get(u.rstrip("/")) == kind]
            # one finding marks one sector row of a page type: the first of its rows that names its rule (DECISIONS 325)
            if not urls or a.claims.setdefault((x["f"].get("id"), kind), row["id"]) != row["id"]:
                continue
        else:  # a host-level finding names hosts, read or not: all of them (DECISIONS 325)
            urls = x["urls"] if x["host"] or not x["read"] else x["read"]
        rel.append((x, urls))
    acted = [(x, u) for x, u in rel if not x["waiting"] and x["measured"]]
    tentative = [(x, u) for x, u in rel if x["waiting"] or not x["measured"]]
    out = {"durum": "Kontrol Edilmedi", "reason": "", "spread": None, "effort": None, "example": None, "evidence": "",
           "maya_action": "", "owner": ""}
    if acted:
        def fault(x):  # a confirmed issue of Blocker/High/Medium; a future problem (a valid certificate) only at High+
            limit = ("S1", "S2") if (x["f"].get("rule_id") or "") in FUTURE_RULES else SEVERE
            return x["sev"] in limit and x["kind"] == "issue"
        out["durum"] = "Hatalı" if any(fault(x) for x, _ in acted) else "Kısmen Uygun"
        rules = sorted({x["f"].get("rule_id") or x["f"].get("check_id") or "" for x, _ in acted})
        out["reason"] = REASON["found"].format(rules=", ".join(rules))
        total = a.count.get(kind, 0) if kind is not None else len(a.read)
        out["spread"] = max((_spread(len(u), total) if u and kind != "home" and not x["host"] else 5) for x, u in acted)
        notes = [note(x["f"].get("check_id") or "", x["f"].get("title") or "") for x, _ in acted]
        out["effort"] = max(EFFORT.get(n["effort"], 3) for n in notes)
        out["owner"] = " + ".join(dict.fromkeys(OWNERS.get(n["owner"], n["owner"]) for n in notes))
        urls = [u for _, us in acted for u in us]
        out["example"] = a.best_page(urls)
        lines = []
        for x, us in sorted(acted, key=lambda p: ("S1", "S2", "S3", "S4").index(p[0]["sev"]))[:3]:
            n = _hosts(us) if x["host"] else len(us)
            line = a.name(x["f"]) + ((f" ({n} alan adı)" if x["host"] else f" ({n} sayfa)") if n else "")
            ex = a.best_page(us)
            if ex:
                value = measured(x["f"], ex, "tr", page=a.measures.get(ex.rstrip("/")), read=ex.rstrip("/") in a.read)
                if value and value != "—":
                    line += f"; örnek {ex}: {value}"
            lines.append(line)
        out["evidence"] = "\n".join(lines)
        out["maya_action"] = "\n".join(dict.fromkeys(a.fix(x["f"]) for x, _ in acted if a.fix(x["f"])))[:2000]
        return out
    if tentative:
        total = a.count.get(kind, 0) if kind is not None else len(a.read)  # the measured spread, kept as a default
        out["spread"] = max((_spread(len(u), total) if u and kind != "home" and not x["host"] else 5) for x, u in tentative)
        rules = ", ".join(sorted({x["f"].get("rule_id") or "" for x, _ in tentative}))
        out["reason"] = REASON["waiting" if any(x["waiting"] for x, _ in tentative) else "tentative"].format(rules=rules)
        return out
    if kind is not None:
        out["example"] = a.top_of_type(kind)
    if st in ("G", "P") or st.startswith("M"):
        out["reason"] = REASON[st[0]]
        return out
    states = [a.checks.get(c) for c in row["needs"]]
    if row["needs"] and all(s == "not_applicable" for s in states):
        out["durum"], out["reason"] = "Uygulanamaz", REASON["na"]
        return out
    if not row["needs"] or any(s in (None, "not_assessed") for s in states):
        out["reason"] = REASON["not_run"]
        return out
    if st == "K":
        out["reason"] = REASON["partly"].format(covered=row["covered"], missing=row["missing"] or "—")
        return out
    if a.low:
        out["reason"] = REASON["low"]
        return out
    out["durum"] = "Uygun"
    out["reason"] = (REASON["clean_partial"] if any(s == "partial" for s in states) else REASON["clean"]).format(covered=row["covered"])
    # DECISIONS 325: what was checked, and on how many pages or host names
    what, unit = row.get("checked") or (row["covered"], "page")
    if unit == "host":
        out["evidence"] = REASON["checked_host"].format(n=a.hosts, what=what)
    elif kind is not None:
        out["evidence"] = REASON["checked_type"].format(n=a.count.get(kind, 0), type=row["page_type"], what=what)
    else:
        out["evidence"] = REASON["checked_pages"].format(n=len(a.read), what=what)
    return out


def evaluate(report: dict, selection: dict, lists: dict | None = None, business: str | None = None, *,
             title: Callable | None = None, words: Callable | None = None) -> dict:
    """{"sector", "profile", "core": [row + result], "sec": [row + result or None], "types": [...]} for one audit."""
    a = _Audit(report, selection, lists, business, title, words)
    m = method()
    core = [{**row, **_evaluate(a, row, None)} for row in m["core"]]
    sec = []
    for row in m["sec"]:
        if a.sector and row["sector"] == a.sector:
            if a.count.get(row["type_id"], 0):
                sec.append({**row, **_evaluate(a, row, row["type_id"])})
            else:
                sec.append({**row, **prefill(row, {"durum": "Kontrol Edilmedi", "reason": REASON["type"], "spread": None,
                                                    "effort": None, "example": None, "evidence": "", "maya_action": "",
                                                    "owner": ""})})
        else:
            sec.append({**row, **prefill(row, {"durum": "Kontrol Edilmedi", "reason": REASON["sector"] if a.sector else REASON["no_sector"],
                                                "spread": None, "effort": None, "example": None, "evidence": "",
                                                "maya_action": "", "owner": ""}), "_other": True})
    order = {d: i for i, d in enumerate(("Hatalı", "Kısmen Uygun", "Uygun", "Uygulanamaz", "Kontrol Edilmedi"))}
    types = []
    for t in m["page_types"]:
        state, example = "Kontrol Edilmedi", None
        if a.sector and t["sector"] == a.sector:
            mine = [r for r in sec if r["sector"] == t["sector"] and r["page_type"] == t["page_type"]]
            done = [r["durum"] for r in mine if r["durum"] != "Kontrol Edilmedi"]
            state = min(done, key=order.get) if done else "Kontrol Edilmedi"
            example = a.top_of_type(t["type_id"])
        types.append({**t, "durum": state, "example": example})
    own = [r for r in sec if not r.get("_other")]
    filled = sum(1 for r in core + own if r["durum"] != "Kontrol Edilmedi")
    return {"sector": a.sector, "profile": a.profile, "core": core, "sec": sec, "types": types,
            "filled": filled, "rows": len(core) + len(own)}


# ------------------------------------------------------------------------------------------------- the workbook

def _score(impact, weight, spread, effort, durum):
    """The team's score formula (Sektörel: with weight; Ortak: weight 1), worked out for the cached value."""
    if durum in ("Kontrol Edilmedi", "Uygulanamaz") or spread in (None, "") or effort in (None, ""):
        return ""
    if durum == "Uygun":
        return 0
    return round(20 * impact * (weight if weight not in (None, "") else 1) * spread * (1 if durum == "Hatalı" else 0.5) / effort, 1)


def _level(score):
    if score == "":
        return ""
    if score == 0:
        return "Yok"
    return "P0" if score >= 160 else "P1" if score >= 80 else "P2" if score >= 30 else "P3"


def _url(u: str | None):
    return {"text": u, "link": u} if u and u.startswith(("http://", "https://")) else (u or "")


def sheets(result: dict) -> list[dict]:
    m = method()
    H = m["headers"]
    weights = {r[0]: r[1] for r in m["methodology"][21:27]}  # Metodoloji!A22:B27, rank -> weight
    meth = {"name": "Metodoloji", "header": [x if x is not None else "" for x in m["methodology"][0]],
            "rows": [[x if x is not None else "" for x in r] for r in m["methodology"][1:]] + [[], PREFILL_NOTE], "widths": [28, 120],
            "frozen": False, "filter": False}
    last_type = len(result["types"]) + 1
    trows = []
    for i, t in enumerate(result["types"], 2):
        w = weights.get(t["rank"], "")
        trows.append([t["sector"], t["rank"], t["page_type"],
                      {"formula": f'=IFERROR(VLOOKUP(B{i},Metodoloji!$A$22:$B$27,2,FALSE),"")', "value": w},
                      t["note"], _url(t.get("example")), t["durum"]])
    types = {"name": "Sektör Önceliği", "header": H["types"], "rows": trows, "widths": [28, 10, 34, 10, 44, 50, 18],
             "validations": [{"ref": f"G2:G{last_type}", "list": DURUM}]}
    crows = []
    for i, r in enumerate(result["core"], 2):
        sc = _score(r["impact"], None, r["spread"], r["effort"], r["durum"])
        crows.append([r["id"], r["group"], r["check"], r["how"], r["criterion"], r["tool"], r["impact"],
                      r["spread"] if r["spread"] is not None else "", r["effort"] if r["effort"] is not None else "", r["durum"],
                      {"formula": f'=IF(OR(J{i}="Kontrol Edilmedi",J{i}="Uygulanamaz",H{i}="",I{i}=""),"",IF(J{i}="Uygun",0,'
                                  f'ROUND(20*G{i}*H{i}*IF(J{i}="Hatalı",1,0.5)/I{i},1)))', "value": sc},
                      {"formula": f'=IF(K{i}="","",IF(K{i}=0,"Yok",IF(K{i}>=160,"P0",IF(K{i}>=80,"P1",IF(K{i}>=30,"P2","P3")))))',
                       "value": _level(sc)},
                      _url(r["example"]), r["evidence"], r["maya_action"] or r.get("action") or "", r["owner"],
                      r["reason"], STATUS[r["status"]], ", ".join(r["rules"]), ""])
    last_core = len(crows) + 1
    core = {"name": "Ortak SEO Kontrolleri", "header": H["core"] + EXTRA, "rows": crows,
            "widths": [13, 22, 34, 66, 59, 26, 8, 10, 8, 18, 12, 10, 42, 60, 64, 20, 60, 22, 30, 20],
            "validations": [{"ref": f"H2:I{last_core}", "list": ["1", "2", "3", "4", "5"]},
                            {"ref": f"J2:J{last_core}", "list": DURUM}]}
    srows = []
    for i, r in enumerate(result["sec"], 2):
        sc = _score(r["impact"], r["weight"], r["spread"], r["effort"], r["durum"])
        srows.append([r["id"], r["sector"], r["rank"], r["page_type"], r["dimension"], r["check"], r["how"], r["criterion"],
                      r["tool"], r["impact"],
                      {"formula": f'=IFERROR(VLOOKUP(C{i},Metodoloji!$A$22:$B$27,2,FALSE),"")', "value": weights.get(r["rank"], "")},
                      r["spread"] if r["spread"] is not None else "", r["effort"] if r["effort"] is not None else "", r["durum"],
                      {"formula": f'=IF(OR(N{i}="Kontrol Edilmedi",N{i}="Uygulanamaz",L{i}="",M{i}=""),"",IF(N{i}="Uygun",0,'
                                  f'ROUND(20*J{i}*K{i}*L{i}*IF(N{i}="Hatalı",1,0.5)/M{i},1)))', "value": sc},
                      {"formula": f'=IF(O{i}="","",IF(O{i}=0,"Yok",IF(O{i}>=160,"P0",IF(O{i}>=80,"P1",IF(O{i}>=30,"P2","P3")))))',
                       "value": _level(sc)},
                      _url(r["example"]), r["evidence"], r["maya_action"] or r.get("action") or "", r["owner"],
                      r["reason"], STATUS[r["status"]], ", ".join(r["rules"]), m["draft_note"] if r.get("draft") else ""])
    last_sec = len(srows) + 1
    sec = {"name": "Sektörel SEO Kontrolleri", "header": H["sec"] + EXTRA, "rows": srows,
           "widths": [9, 22, 9, 26, 22, 36, 68, 62, 29, 7, 9, 10, 7, 18, 10, 9, 45, 60, 68, 20, 60, 22, 30, 34],
           "validations": [{"ref": f"L2:M{last_sec}", "list": ["1", "2", "3", "4", "5"]},
                           {"ref": f"N2:N{last_sec}", "list": DURUM}]}
    # Audit Özeti: the team's layout (title, totals, a blank row, the header on row 5, a row per sector)
    S = "'Sektörel SEO Kontrolleri'"
    T = "'Sektör Önceliği'"
    srange, nrange, prange = f"{S}!$B$2:$B${last_sec}", f"{S}!$N$2:$N${last_sec}", f"{S}!$P$2:$P${last_sec}"
    base = [r for r in result["sec"] if not r.get("draft")]
    rows = [["Toplam sektör", sum(1 for s in m["sectors"] if not s["draft"]), "Öncelikli sayfa türü",
             sum(1 for t in result["types"] if not t.get("draft"))],
            ["Ortak SEO kontrolü", len(result["core"]), "Sektörel SEO kontrolü", len(base)], [], H["summary"]]
    for k, s in enumerate(m["sectors"]):
        i = 6 + k
        mine = [r for r in result["sec"] if r["sector"] == s["name"]]
        cnt = {d: sum(1 for r in mine if r["durum"] == d) for d in DURUM}
        lv = [_level(_score(r["impact"], r["weight"], r["spread"], r["effort"], r["durum"])) for r in mine]
        done = cnt["Hatalı"] + cnt["Kısmen Uygun"] + cnt["Uygun"]
        rows.append([s["name"],
                     {"formula": f"=COUNTIF({T}!$A$2:$A${last_type},A{i})", "value": sum(1 for t in result["types"] if t["sector"] == s["name"])},
                     {"formula": f"=COUNTIF({srange},A{i})", "value": len(mine)},
                     {"formula": f"=SUM(E{i}:G{i})", "value": done},
                     {"formula": f'=COUNTIFS({srange},A{i},{nrange},"Hatalı")', "value": cnt["Hatalı"]},
                     {"formula": f'=COUNTIFS({srange},A{i},{nrange},"Kısmen Uygun")', "value": cnt["Kısmen Uygun"]},
                     {"formula": f'=COUNTIFS({srange},A{i},{nrange},"Uygun")', "value": cnt["Uygun"]},
                     {"formula": f'=COUNTIFS({srange},A{i},{prange},"P0")', "value": lv.count("P0")},
                     {"formula": f'=COUNTIFS({srange},A{i},{prange},"P1")', "value": lv.count("P1")},
                     {"formula": f"=IFERROR(D{i}/C{i},0)", "value": round(done / len(mine), 4) if mine else 0}])
    rows.append([])
    rows.append([m["summary_note"]])
    rows.append([f"Taslak satırlar (Havayolu, Restoran / kafe): {m['draft_note']}."])
    rows.append([f"Maya bu dosyayı bu denetimden doldurdu: {result['filled']} / {result['rows']} satır "
                 f"(44 ortak + bu sektörün kontrolleri). «Kontrol Edilmedi» satırlarının nedeni «Maya: Durum nedeni» sütunundadır."])
    summary = {"name": "Audit Özeti", "header": ["SEO AUDIT | SEKTÖREL KAPSAM VE İLERLEME"], "rows": rows,
               "widths": [44, 12, 16, 12, 10, 14, 10, 8, 8, 14], "frozen": False, "filter": False}
    return [meth, types, core, sec, summary]


def build(report: dict, selection: dict, lists: dict | None = None, business: str | None = None, *,
          title: Callable | None = None, words: Callable | None = None) -> bytes:
    """The workbook's bytes."""
    return xlsx.workbook(sheets(evaluate(report, selection, lists, business, title=title, words=words)))
