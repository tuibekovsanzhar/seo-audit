"""A small XLSX (Office Open XML) writer: text and number cells, a bold frozen header, column widths, a filter,
wrapped text and clickable links (DECISIONS 322); formula cells with their computed value, and list dropdowns
(DECISIONS 324: the team's sector audit workbook recalculates when a teammate edits a row).

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


# Cell styles (xl/styles.xml): 0 plain, 1 header (bold, grey, wrapped), 2 wrapped text, 3 link (blue, underlined,
# wrapped), 4 a title line (bold, larger). DECISIONS 322: every text cell wraps, so long problem lists stay readable.
# DECISIONS 376: 5 the Maya band (white bold on the brand colour), 6 the band's second line (not wrapped, so it runs
# across the empty cells beside it), 7 the band's "← Kapak" link, 8 a green header (Search Console and AI columns),
# 9 an expert or client input cell (pale yellow, kept when empty), 10 a cell Maya computed (pale blue).
PLAIN, HEADER, WRAP, LINK, TITLE = 0, 1, 2, 3, 4
BAND, BAND_NOTE, BAND_LINK, HEADER_GREEN, INPUT, COMPUTED = 5, 6, 7, 8, 9, 10
# DECISIONS 377: 11 a share or rate stored as a fraction and shown as a percentage with one decimal ("0.0%": Excel shows
# %17,6 in a Turkish locale, 17.6% in an English one)
PERCENT = 11
BAND_STYLES = (BAND, BAND_NOTE, BAND_LINK)
STYLE_OF = {"green": HEADER_GREEN, "input": INPUT, "computed": COMPUTED, "header": HEADER, "title": TITLE, "percent": PERCENT}
MAX_LINKS = 65000  # Excel keeps at most 65,530 hyperlinks per sheet; past that a cell is plain text
MAX_LINK_LENGTH = 2000  # Excel refuses a hyperlink address longer than 2,079 characters


def _formula(ref: str, value: dict, s: str) -> str:
    """A formula cell with its value worked out by the writer (shown as is by readers that do not calculate; Excel
    and LibreOffice calculate again on opening, `fullCalcOnLoad`)."""
    f = escape(_BAD.sub("", str(value["formula"])).lstrip("="))
    v = value.get("value")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f'<c r="{ref}"{s}><f>{f}</f><v>{v}</v></c>'
    return f'<c r="{ref}"{s} t="str"><f>{f}</f><v>{escape(_BAD.sub("", str(v or "")))}</v></c>'


def _cell(ref: str, value: Any, style: int = 0) -> str:
    s = f' s="{style}"' if style else ""
    if isinstance(value, dict) and "formula" in value:
        return _formula(ref, value, s)
    if isinstance(value, dict):
        value = value.get("text")
    if value is None or value == "":
        return f'<c r="{ref}"{s}/>' if style == INPUT else ""  # an input cell keeps its colour while empty
    if isinstance(value, bool):
        value = "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{s}><v>{value}</v></c>'
    text = _BAD.sub("", str(value))[:MAX_CELL]
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _link_of(value: Any) -> tuple[str, str] | None:
    """("external", address) or ("location", "'Sheet'!A5") for a cell written as {"text", "link"|"location"}."""
    if not isinstance(value, dict) or value.get("text") in (None, ""):
        return None
    link = value.get("link")
    if isinstance(link, str) and link.startswith(("http://", "https://")) and len(link) <= MAX_LINK_LENGTH and not _BAD.search(link):
        return "external", link
    if isinstance(value.get("location"), str) and value["location"]:
        return "location", value["location"]
    return None


def _shift_ref(ref: str, by: int) -> str:
    """"N2:N208" -> "N4:N210": a cell or range moved down `by` rows (the Maya band above the header, DECISIONS 376)."""
    return re.sub(r"([A-Z]+)(\d+)", lambda m: f"{m.group(1)}{int(m.group(2)) + by}", ref) if by else ref


LOCATION = re.compile(r"^(?P<sheet>'(?:[^']|'')+'|[^'!]+)!(?P<col>\$?[A-Z]+)\$?(?P<row>\d+)$")


def location_target(location: str) -> tuple[str, str, int] | None:
    """("Sheet", "A", 5) for "'Sheet'!A5", None when it is not one cell of a sheet."""
    m = LOCATION.match(location or "")
    if not m:
        return None
    name = m.group("sheet")
    if name.startswith("'"):
        name = name[1:-1].replace("''", "'")
    return name, m.group("col").lstrip("$"), int(m.group("row"))


def _sheet(header: list[str], rows: Iterable[list[Any]], widths: list[int] | None, *, frozen: bool = True,
           filter: bool = True, wrap: bool = True, title_rows: int = 0,
           validations: list[dict] | None = None, band: list[list[Any]] | None = None,
           row_styles: dict[int, str] | None = None, col_styles: dict[int, str] | None = None,
           header_styles: dict[int, str] | None = None) -> tuple[str, list[str]]:
    """(the worksheet's XML, the external link targets in order: relationship rId1, rId2, ...).

    DECISIONS 376: `band`, rows written above the header (the Maya band: its first cell styled BAND, then BAND_NOTE or
    BAND_LINK), which move the header, the frozen pane, the filter and the dropdowns down; `row_styles` {body row
    index: "header"|"title"} styles a whole body row (a table header or a heading inside a sheet); `col_styles`
    {column index: "input"|"computed"} colours a body column; `header_styles` {column index: "green"} a header cell."""
    rows = list(rows)
    band = [list(b) for b in band or []]
    top = len(band)
    cols = max([len(header)] + [len(r) for r in rows] + [len(b) for b in band]) or 1
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">']
    out.append('<sheetViews><sheetView workbookViewId="0">' + (
        f'<pane ySplit="{top + 1}" topLeftCell="A{top + 2}" activePane="bottomLeft" state="frozen"/>' if frozen and header else "")
        + "</sheetView></sheetViews>")
    if widths:
        out.append("<cols>" + "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
                                      for i, w in enumerate(widths, 1)) + "</cols>")
    out.append("<sheetData>")
    links: list[tuple[str, str, str, str]] = []  # (ref, kind, target, text)
    for r, values in enumerate(band, 1):  # DECISIONS 376: the Maya band
        cells = []
        for c, v in enumerate(values, 1):
            ref = f"{_col(c)}{r}"
            link = _link_of(v) if c > 1 or r > 1 else None
            if link:
                links.append((ref, link[0], link[1], str(v.get("text"))))
            cells.append(_cell(ref, v, BAND if r == 1 and c == 1 else BAND_LINK if link else BAND_NOTE))
        out.append(f'<row r="{r}">{"".join(cells)}</row>')
    body = ([header] if header else []) + rows
    row_styles, col_styles, header_styles = row_styles or {}, col_styles or {}, header_styles or {}
    for r, values in enumerate(body, 1):
        cells = []
        i = r - 1 - (1 if header else 0)  # the body row's index (-1: the header)
        if col_styles and i >= 0 and i not in row_styles and len(values) <= max(col_styles):
            values = list(values) + [""] * (max(col_styles) + 1 - len(values))
        for c, v in enumerate(values, 1):
            ref = f"{_col(c)}{r + top}"
            link = None
            if r == 1 and header:
                style = STYLE_OF.get(header_styles.get(c - 1, ""), HEADER)
            elif i in row_styles:
                link = _link_of(v) if len(links) < MAX_LINKS else None
                style = LINK if link else STYLE_OF.get(row_styles[i], HEADER)
            elif r <= title_rows + (1 if header else 0) and c == 1:
                style = TITLE
            else:
                link = _link_of(v) if len(links) < MAX_LINKS else None
                style = LINK if link else STYLE_OF.get(col_styles.get(c - 1, ""),
                                                       WRAP if wrap and isinstance(v, (str, dict)) else PLAIN)
            if link:
                links.append((ref, link[0], link[1], str(v.get("text"))))
            cells.append(_cell(ref, v, style))
        out.append(f'<row r="{r + top}">{"".join(cells)}</row>')
    out.append("</sheetData>")
    if filter and header:
        out.append(f'<autoFilter ref="A{top + 1}:{_col(cols)}{len(rows) + 1 + top}"/>')
    if validations:  # list dropdowns: {"ref": "N2:N208", "list": ["Uygun", ...]} (DECISIONS 324)
        out.append(f'<dataValidations count="{len(validations)}">')
        for v in validations:
            items = ",".join(str(x).replace('"', "") for x in v["list"])
            out.append(f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" sqref="{escape(_shift_ref(v["ref"], top))}">'
                       f'<formula1>{escape(chr(34) + items + chr(34))}</formula1></dataValidation>')
        out.append("</dataValidations>")
    targets: list[str] = []
    if links:
        out.append("<hyperlinks>")
        for ref, kind, target, text in links:
            if kind == "external":
                targets.append(target)
                out.append(f'<hyperlink ref="{ref}" r:id="rId{len(targets)}"/>')
            else:
                out.append(f'<hyperlink ref="{ref}" location="{escape(target, {chr(34): "&quot;"})}" '
                           f'display="{escape(text[:250], {chr(34): "&quot;"})}"/>')
        out.append("</hyperlinks>")
    out.append("</worksheet>")
    return "".join(out), targets


def _safe_name(name: str, used: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", " ", name).strip()[:31] or "Sheet"
    candidate, n = base, 2
    while candidate in used:
        candidate = f"{base[:28]} {n}"
        n += 1
    used.add(candidate)
    return candidate


def workbook(sheets: list[dict], properties: dict | None = None) -> bytes:
    """`sheets`: [{"name", "header": [...], "rows": [[...], ...], "widths": [...]}] -> the .xlsx file's bytes.

    Optional per sheet: "frozen" and "filter" (default True: the header row stays in view and has filter buttons),
    "wrap" (default True), "title_rows" (that many first rows after the header are bold titles). A cell may be
    {"text": ..., "link": "https://..."} (a clickable address) or {"text": ..., "location": "'Sheet'!A5"} (a link to
    a cell of this file), or {"formula": "=SUM(A1:A3)", "value": 6} (a formula and its value). Optional per sheet:
    "validations" ([{"ref", "list"}]: a dropdown of those values). `properties`: the file's document properties
    ({"creator", "version", "description", "created"}, DECISIONS 375), written to docProps/core.xml."""
    sheets = [{**s, "rows": list(s["rows"])} for s in sheets]  # read twice below (formulas, then cells)
    # DECISIONS 376: a link to a cell of a sheet with the Maya band moves down with that sheet's rows; the builders
    # write every link as if the header were row 1
    tops = {s["name"]: len(s.get("band") or []) for s in sheets}
    if any(tops.values()):
        def moved(v):
            if isinstance(v, dict) and isinstance(v.get("location"), str):
                t = location_target(v["location"])
                if t and tops.get(t[0]):
                    quoted = "'" + t[0].replace("'", "''") + "'"
                    return {**v, "location": f"{quoted}!{t[1]}{t[2] + tops[t[0]]}"}
            return v
        sheets = [{**s, "rows": [[moved(v) for v in r] for r in s["rows"]]} for s in sheets]
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
                             for i in range(1, len(sheets) + 1))
                   + ('<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                      if properties else "") + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   + ('<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                      if properties else "") + "</Relationships>")
        if properties:
            props = {k: escape(str(v)) for k, v in properties.items() if v is not None}
            z.writestr("docProps/core.xml",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                       'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                       'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                       + (f"<dc:creator>{props['creator']}</dc:creator>" if "creator" in props else "")
                       + (f"<dc:description>{props['description']}</dc:description>" if "description" in props else "")
                       + (f"<cp:version>{props['version']}</cp:version>" if "version" in props else "")
                       + (f'<dcterms:created xsi:type="dcterms:W3CDTF">{props["created"]}</dcterms:created>' if "created" in props else "")
                       + "</cp:coreProperties>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(n, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>'
                             for i, n in enumerate(names, 1)) + "</sheets>"
                   # formulas are calculated again when the file is opened (DECISIONS 324)
                   + ('<calcPr calcId="191029" fullCalcOnLoad="1"/>' if any(
                       isinstance(v, dict) and "formula" in v for s in sheets for r in s["rows"] for v in r) else "")
                   + "</workbook>")
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
                   '<numFmts count="1"><numFmt numFmtId="164" formatCode="0.0%"/></numFmts>'
                   '<fonts count="6"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font>'
                   '<font><u/><sz val="11"/><color rgb="FF0563C1"/><name val="Calibri"/></font>'
                   '<font><b/><sz val="13"/><name val="Calibri"/></font>'
                   '<font><b/><sz val="12"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
                   '<font><sz val="10"/><color rgb="FF555B6E"/><name val="Calibri"/></font></fonts>'
                   '<fills count="7"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
                   '<fill><patternFill patternType="solid"><fgColor rgb="FFE7E9EE"/><bgColor indexed="64"/></patternFill></fill>'
                   '<fill><patternFill patternType="solid"><fgColor rgb="FF3B2A8C"/><bgColor indexed="64"/></patternFill></fill>'
                   '<fill><patternFill patternType="solid"><fgColor rgb="FFDDF0DC"/><bgColor indexed="64"/></patternFill></fill>'
                   '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF4C8"/><bgColor indexed="64"/></patternFill></fill>'
                   '<fill><patternFill patternType="solid"><fgColor rgb="FFE3EEFB"/><bgColor indexed="64"/></patternFill></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="12"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                   '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1">'
                   '<alignment vertical="top" wrapText="1"/></xf>'
                   '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
                   '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
                   '<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
                   # DECISIONS 376: 5 band, 6 band note, 7 band link, 8 green header, 9 input, 10 computed
                   '<xf numFmtId="0" fontId="4" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
                   '<xf numFmtId="0" fontId="5" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
                   '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
                   '<xf numFmtId="0" fontId="1" fillId="4" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1">'
                   '<alignment vertical="top" wrapText="1"/></xf>'
                   '<xf numFmtId="0" fontId="0" fillId="5" borderId="0" xfId="0" applyFill="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
                   '<xf numFmtId="0" fontId="0" fillId="6" borderId="0" xfId="0" applyFill="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
                   '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment vertical="top"/></xf>'
                   "</cellXfs>"
                   '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                   "</styleSheet>")
        for i, s in enumerate(sheets, 1):
            xml, targets = _sheet(s["header"], s["rows"], s.get("widths"), frozen=s.get("frozen", True),
                                  filter=s.get("filter", True), wrap=s.get("wrap", True), title_rows=s.get("title_rows", 0),
                                  validations=s.get("validations"), band=s.get("band"), row_styles=s.get("row_styles"),
                                  col_styles=s.get("col_styles"), header_styles=s.get("header_styles"))
            z.writestr(f"xl/worksheets/sheet{i}.xml", xml)
            if targets:
                z.writestr(f"xl/worksheets/_rels/sheet{i}.xml.rels",
                           '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                           '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                           + "".join(f'<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                                     f'Target="{escape(t, {chr(34): "&quot;"})}" TargetMode="External"/>'
                                     for n, t in enumerate(targets, 1))
                           + "</Relationships>")
    return buf.getvalue()


def read(data: bytes | str | Path, band: bool = False) -> dict[str, list[list[str]]]:
    """{sheet name: rows of cell text}, for tests and checks of a file this module wrote. The Maya band above a
    sheet's header (DECISIONS 376) is left out unless `band`: row 0 is the header, as before the band."""
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
            heading = True
            for row in root.iter(f"{{{ns['m']}}}row"):
                first = row.find("m:c", ns)
                if heading and not band and (first is None or first.get("s") in {str(x) for x in BAND_STYLES}):
                    continue
                heading = False
                values: dict[int, str] = {}
                for c in row:
                    ref = re.match(r"[A-Z]+", c.get("r")).group(0)
                    n = 0
                    for ch in ref:
                        n = n * 26 + ord(ch) - 64
                    t = c.find(".//m:t", ns)
                    v = c.find("m:v", ns)
                    values[n] = t.text if t is not None else ((v.text or "") if v is not None else "")
                rows.append([values.get(k, "") for k in range(1, max(values, default=0) + 1)])
            out[sheet.get("name")] = rows
    return out


def read_any(data: bytes | str | Path) -> dict[str, list[list[str]]]:
    """{sheet name: rows of cell text} of any .xlsx, also one Excel, LibreOffice or Google Sheets saved (DECISIONS 353:
    the SEO team's edited catalogue): sheets found through the workbook's relationships, shared strings, inline and
    rich text, numbers and formulas' cached values. No style, no date conversion: text as written."""
    import posixpath
    import xml.etree.ElementTree as ET
    m = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    r_id = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    rel = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    source = io.BytesIO(data) if isinstance(data, bytes) else data
    out: dict[str, list[list[str]]] = {}
    with zipfile.ZipFile(source) as z:
        names = set(z.namelist())

        def text_of(node) -> str:
            return "".join(t.text or "" for t in node.iter(f"{m}t"))
        shared = ([text_of(si) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{m}si")]
                  if "xl/sharedStrings.xml" in names else [])
        targets = {}
        if "xl/_rels/workbook.xml.rels" in names:
            for x in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).findall(f"{rel}Relationship"):
                target = x.get("Target") or ""
                targets[x.get("Id")] = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
        book = ET.fromstring(z.read("xl/workbook.xml"))
        for i, sheet in enumerate(book.find(f"{m}sheets"), 1):
            part = targets.get(sheet.get(r_id)) or f"xl/worksheets/sheet{i}.xml"
            if part not in names:
                continue
            rows = []
            for row in ET.fromstring(z.read(part)).iter(f"{m}row"):
                values: dict[int, str] = {}
                for n_auto, c in enumerate(row.findall(f"{m}c"), 1):
                    ref = re.match(r"[A-Z]+", c.get("r") or "")
                    n = 0
                    if ref:
                        for ch in ref.group(0):
                            n = n * 26 + ord(ch) - 64
                    else:
                        n = max(values, default=0) + 1
                    kind, v = c.get("t"), c.find(f"{m}v")
                    if kind == "s" and v is not None and (v.text or "").isdigit() and int(v.text) < len(shared):
                        values[n] = shared[int(v.text)]
                    elif kind == "inlineStr":
                        values[n] = text_of(c)
                    else:
                        values[n] = (v.text or "") if v is not None else text_of(c)
                rows.append([values.get(k, "") for k in range(1, max(values, default=0) + 1)])
            out[sheet.get("name")] = rows
    return out


def links(data: bytes | str | Path) -> dict[str, dict[str, str]]:
    """{sheet name: {cell reference: link}} of a file this module wrote: an external address, or "#'Sheet'!A5" for a
    link inside the file. For tests and checks."""
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
          "p": "http://schemas.openxmlformats.org/package/2006/relationships"}
    source = io.BytesIO(data) if isinstance(data, bytes) else data
    out: dict[str, dict[str, str]] = {}
    with zipfile.ZipFile(source) as z:
        names = set(z.namelist())
        book = ET.fromstring(z.read("xl/workbook.xml"))
        for i, sheet in enumerate(book.find("m:sheets", ns), 1):
            root = ET.fromstring(z.read(f"xl/worksheets/sheet{i}.xml"))
            rels_name = f"xl/worksheets/_rels/sheet{i}.xml.rels"
            rels = ({r.get("Id"): r.get("Target") for r in ET.fromstring(z.read(rels_name)).findall("p:Relationship", ns)}
                    if rels_name in names else {})
            found = {}
            for h in root.iter(f"{{{ns['m']}}}hyperlink"):
                rid = h.get(f"{{{ns['r']}}}id")
                found[h.get("ref")] = rels.get(rid, "") if rid else "#" + (h.get("location") or "")
            out[sheet.get("name")] = found
    return out
