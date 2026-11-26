"""The SEO team's method for each checklist item, from their SEO_Audit_Checklist.xlsx (DECISIONS 378).

checklist_items.json holds each item's id, name, priority and Maya mapping; this file adds the team's own columns:
how to check it ("NASIL KONTROL EDİLİR?"), the pass condition ("Beklenen / geçme koşulu"), the action when it fails,
the tool, and the frequency. Columns are found by their header text, never by position.

Run: python scripts/checklist_method.py "<path>/SEO_Audit_Checklist.xlsx"  (writes maya_audit/checklist_method.json)
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maya_audit import xlsx  # noqa: E402

OUT = ROOT / "maya_audit" / "checklist_method.json"
HEADERS = {"id": "ID", "how": "NASIL KONTROL EDİLİR?", "pass": "Beklenen / geçme koşulu",
           "action": "Hata varsa yapılacak aksiyon", "tool": "Araç / veri", "frequency": "Önerilen sıklık"}
# Every pass condition in the team's file ends with the same sentence; it is kept once, not on 165 rows.
COMMON_PASS = ("Gerekli veri yoksa “Veri eksik”; karar belirsizse “İnceleme gerekli”; siteye uygun değilse gerekçeli "
               "“Uygulanmaz” olarak raporla.")
METHOD = re.compile(r"\s*Kontrol yöntemi:\s*(.+)$")
SHARED = re.compile(r"Ortak testi (SEO-\d{3}) altında çalıştır")
ABOUT = ("DECISIONS 378: the SEO team's own method for each checklist item (their SEO_Audit_Checklist.xlsx), made by "
         "scripts/checklist_method.py: \"pass\" is the team's pass condition (\"Beklenen / geçme koşulu\"), \"method\" "
         "the team's way of checking (\"Kontrol yöntemi\"), \"shared_test\" the item whose test covers this one. "
         "Every pass condition also carries common_pass.")


def _norm(text: str) -> str:
    return " ".join(str(text or "").split()).casefold()


def split_how(how: str) -> tuple[str, str, str | None]:
    """("how to check", "method", shared item) from the team's "NASIL KONTROL EDİLİR?" cell."""
    m = METHOD.search(how or "")
    if not m:
        return (how or "").strip(), "", None
    method = m.group(1).strip()
    shared = SHARED.search(method)
    return how[:m.start()].strip(), method.split(".")[0].strip(), shared.group(1) if shared else None


def item(how: str, pass_: str, action: str = "", tool: str = "", frequency: str = "") -> dict:
    steps, method, shared = split_how(how)
    passed = (pass_ or "").strip()
    if passed.endswith(COMMON_PASS):
        passed = passed[:-len(COMMON_PASS)].strip()
    out = {"pass": passed, "method": method}
    if shared:
        out["shared_test"] = shared
    out.update({k: v.strip() for k, v in (("how", steps), ("action", action), ("tool", tool), ("frequency", frequency)) if v and v.strip()})
    return out


def build(path: str | Path) -> dict:
    sheets = xlsx.read(Path(path))
    rows = next((r for r in sheets.values() if r and any(_norm(c) == _norm(HEADERS["pass"]) for c in r[0])), None)
    if rows is None:
        raise ValueError(f"{Path(path).name}: no sheet has a {HEADERS['pass']!r} column")
    header = [_norm(c) for c in rows[0]]
    col = {k: header.index(_norm(h)) for k, h in HEADERS.items() if _norm(h) in header}
    if "id" not in col:
        raise ValueError(f"{Path(path).name}: no {HEADERS['id']!r} column")
    cell = lambda r, k: (r[col[k]] if k in col and col[k] < len(r) else "") or ""  # noqa: E731
    items = {}
    for r in rows[1:]:
        if re.fullmatch(r"SEO-\d{3}", cell(r, "id").strip()):
            items[cell(r, "id").strip()] = item(cell(r, "how"), cell(r, "pass"), cell(r, "action"), cell(r, "tool"),
                                                cell(r, "frequency"))
    return {"_about": ABOUT, "source": f"{Path(path).name}, {date.today().isoformat()}", "common_pass": COMMON_PASS,
            "items": dict(sorted(items.items()))}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    OUT.write_text(json.dumps(build(sys.argv[1]), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
