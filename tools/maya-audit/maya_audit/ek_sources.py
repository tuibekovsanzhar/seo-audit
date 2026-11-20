"""DECISIONS 376, phase 5: "Rakip yöntem notları" (the method lines a reader needs for the competitor sheets, beside
them) and "Kaynak eşlemesi" (each sheet of the client Ek: where its data comes from, the period of each source, its
rows). Efsa's file had them by hand; her "row shift" and "change made" columns described her manual copy and do not
apply to a file Maya writes. Turkish, as the team's file. Global for every audit.
"""
from __future__ import annotations

NOTES_NAME = "Rakip yöntem notları"
MAP_NAME = "Kaynak eşlemesi"
RIVAL_SHEETS = ("Rakip - Konu", "Rakip - Sayfa yapısı")
# the "Yöntem" rows that explain the competitor sheets
RIVAL_METHOD = ("Rakip konuları", "Korelasyon", "Maya verisi", "Segment eşikleri", "Önem puanı (0–100)")
RIVAL_WORDS = ("rakip", "konu", "prompt", "citation", "sayfa yapısı", "karşılaştırma")


def notes_sheet(made: list[dict]) -> dict | None:
    """The competitor sheets' method lines, from "Yöntem" and "Kapsam", when the Ek has a competitor sheet."""
    names = {m["name"]: m for m in made}
    if not any(n in names for n in RIVAL_SHEETS):
        return None
    rows = []
    for r in (names.get("Yöntem") or {}).get("rows") or []:
        if r and str(r[0]) in RIVAL_METHOD:
            rows.append(["Yöntem › " + str(r[0]), r[1] if len(r) > 1 else ""])
    for r in (names.get("Kapsam") or {}).get("rows") or []:
        text = str(r[1]) if len(r) > 1 else ""
        if r and r[0] == "Maya verisi" and any(w in text.lower() for w in RIVAL_WORDS):
            rows.append(["Kapsam › Maya verisi", text])
    rows.append(["Okuma", "Konu satırları prompt koşularının payıdır; «Yalnız gösterge (n<10)» işaretli konular karar için "
                          "yeterli değildir. «Fark [HİPOTEZ]» sütunu sayfa yapısı karşılaştırmasıdır, kesin neden değildir."])
    return {"name": NOTES_NAME, "header": ["Kaynak", "Metin"], "rows": rows, "widths": [34, 140], "filter": False,
            "_datasets": sorted({d for n in RIVAL_SHEETS for d in (names.get(n) or {}).get("_datasets") or []}) or None}


def map_sheet(framed: list[dict]) -> dict:
    """One row per sheet of the client Ek (Kapak first): its source line as the band says it, its rows and what it
    is for; the source map itself last."""
    from .ek_frame import ABOUT, key_of
    rows = []
    for m in framed:
        band = m.get("band") or []
        source = next((str(c) for c in (band[1] if len(band) > 1 else []) if str(c).startswith("Kaynak: ")), "")
        k = key_of(m["name"])
        body = [r for r in m.get("rows") or [] if any(str(c.get("text") if isinstance(c, dict) else c).strip() for c in r)]
        rows.append([{"text": m["name"], "location": "'" + m["name"].replace("'", "''") + "'!A1"},
                     source.removeprefix("Kaynak: ") or "Maya Audit (bu dosyanın kendisi)", len(body),
                     (ABOUT.get(k or "") or ("", "", ""))[1]])
    rows.append([MAP_NAME, "Maya Audit (bu dosyanın kendisi)", len(rows), "Her sekmenin kaynağı ve dönemi"])
    return {"name": MAP_NAME, "header": ["Sekme", "Kaynak · dönem", "Satır", "Ne içerir"], "rows": rows,
            "widths": [30, 110, 8, 60], "filter": False}
