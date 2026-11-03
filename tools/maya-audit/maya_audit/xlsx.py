"""A small XLSX (Office Open XML) writer: text and number cells, a bold frozen header, column widths, a filter.

Only the standard library: the project adds no dependency for one file format (AGENTS.md). Enough for the client
report's appendix (DECISIONS 300); Excel, Numbers, LibreOffice and Google Sheets open it.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape

_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
MAX_CELL = 32767  # Excel's limit for one cell's text


def _col(n: int) -> str:
    name = ""
    while n:
        n, r = divmod(n - 1, 26)
        name = chr(65 + r) + name
    return name


def _cell(ref: str, value: Any, style: int = 0) -> str:
    s = f' s="{style}"' if style else ""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        value = "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{s}><v>{value}</v></c>'
    text = _BAD.sub("", str(value))[:MAX_CELL]
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _sheet(header: list[str], rows: Iterable[list[Any]], widths: list[int] | None) -> str:
    rows = list(rows)
    cols = max([len(header)] + [len(r) for r in rows]) or 1
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
           'state="frozen"/></sheetView></sheetViews>']
    if widths:
        out.append("<cols>" + "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
                                      for i, w in enumerate(widths, 1)) + "</cols>")
    out.append("<sheetData>")
    for r, values in enumerate([header] + rows, 1):
        style = 1 if r == 1 else 0
        cells = "".join(_cell(f"{_col(c)}{r}", v, style) for c, v in enumerate(values, 1))
        out.append(f'<row r="{r}">{cells}</row>')
    out.append("</sheetData>")
    out.append(f'<autoFilter ref="A1:{_col(cols)}{len(rows) + 1}"/>')
    out.append("</worksheet>")
    return "".join(out)


def _safe_name(name: str, used: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", " ", name).strip()[:31] or "Sheet"
    candidate, n = base, 2
    while candidate in used:
        candidate = f"{base[:28]} {n}"
        n += 1
    used.add(candidate)
    return candidate


def workbook(sheets: list[dict]) -> bytes:
    """`sheets`: [{"name", "header": [...], "rows": [[...], ...], "widths": [...]}] -> the .xlsx file's bytes."""
    used: set[str] = set()
    names = [_safe_name(s["name"], used) for s in sheets]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(1, len(sheets) + 1)) + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(n, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>'
                             for i, n in enumerate(names, 1)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(sheets) + 1))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   "</Relationships>")
        z.writestr("xl/styles.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
                   '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                   '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
                   "</styleSheet>")
        for i, s in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet(s["header"], s["rows"], s.get("widths")))
    return buf.getvalue()


def read(data: bytes | str | Path) -> dict[str, list[list[str]]]:
    """{sheet name: rows of cell text}, for tests and checks of a file this module wrote."""
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    source = io.BytesIO(data) if isinstance(data, bytes) else data
    out: dict[str, list[list[str]]] = {}
    with zipfile.ZipFile(source) as z:
        book = ET.fromstring(z.read("xl/workbook.xml"))
        for i, sheet in enumerate(book.find("m:sheets", ns), 1):
            root = ET.fromstring(z.read(f"xl/worksheets/sheet{i}.xml"))
            rows = []
            for row in root.iter(f"{{{ns['m']}}}row"):
                values: dict[int, str] = {}
                for c in row:
                    ref = re.match(r"[A-Z]+", c.get("r")).group(0)
                    n = 0
                    for ch in ref:
                        n = n * 26 + ord(ch) - 64
                    t = c.find(".//m:t", ns)
                    v = c.find("m:v", ns)
                    values[n] = t.text if t is not None else (v.text if v is not None else "")
                rows.append([values.get(k, "") for k in range(1, max(values, default=0) + 1)])
            out[sheet.get("name")] = rows
    return out
