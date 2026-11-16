"""A minimal .xlsx writer (an .xlsx file is a zip of XML files).

Covers exactly what the reports need: several sheets, a bold frozen header row,
column widths, text and number cells, and right-to-left sheets for Hebrew.
Text is stored as text, so a student ID such as 012345678 keeps its leading zero.
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.sax.saxutils import escape

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006"
_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
_BAD_NAME = re.compile(r"[\[\]:*?/\\]")

_STYLES = (f'{_HEAD}<styleSheet xmlns="{_NS}">'
           '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
           '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
           '<fills count="2"><fill><patternFill patternType="none"/></fill>'
           '<fill><patternFill patternType="gray125"/></fill></fills>'
           '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
           '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
           '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
           '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
           '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
           '</styleSheet>')


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


class Workbook:
    def __init__(self, rtl: bool = False):
        self._rtl = rtl
        self._sheets: list[tuple[str, list[list], list[int]]] = []

    def add_sheet(self, name: str, rows: list[list], widths: list[int] | None = None) -> None:
        """`rows[0]` is the header. A cell is a number, or anything else (stored as text)."""
        name = _BAD_NAME.sub(" ", name).strip()[:31] or "Sheet"
        taken = {n for n, _, _ in self._sheets}
        base, i = name, 2
        while name in taken:
            suffix = f" ({i})"
            name, i = base[:31 - len(suffix)] + suffix, i + 1
        self._sheets.append((name, rows, widths or []))

    @staticmethod
    def _cell(ref: str, value, style: int) -> str:
        s = f' s="{style}"' if style else ""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f'<c r="{ref}"{s}><v>{value}</v></c>'
        if value is None or value == "":
            return ""
        text = escape(_BAD_XML.sub("", str(value)))
        return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'

    def _sheet_xml(self, rows: list[list], widths: list[int]) -> str:
        rtl = ' rightToLeft="1"' if self._rtl else ""
        out = [f'{_HEAD}<worksheet xmlns="{_NS}"><sheetViews><sheetView workbookViewId="0"{rtl}>'
               '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
               '</sheetView></sheetViews>']
        if widths:
            out.append("<cols>" + "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
                                           for i, w in enumerate(widths, 1)) + "</cols>")
        out.append("<sheetData>")
        for r, row in enumerate(rows, 1):
            cells = "".join(self._cell(f"{column_letter(c)}{r}", v, 1 if r == 1 else 0)
                            for c, v in enumerate(row))
            out.append(f'<row r="{r}">{cells}</row>')
        out.append("</sheetData></worksheet>")
        return "".join(out)

    def to_bytes(self) -> bytes:
        sheets = self._sheets or [("Sheet", [[]], [])]
        n = range(1, len(sheets) + 1)
        content_types = (f'{_HEAD}<Types xmlns="{_PKG}/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Default Extension="xml" ContentType="application/xml"/>'
                         '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                         '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                         + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in n)
                         + "</Types>")
        root_rels = (f'{_HEAD}<Relationships xmlns="{_PKG}/relationships">'
                     f'<Relationship Id="rId1" Type="{_REL}/officeDocument" Target="xl/workbook.xml"/>'
                     '</Relationships>')
        workbook = (f'{_HEAD}<workbook xmlns="{_NS}" xmlns:r="{_REL}"><bookViews><workbookView/></bookViews><sheets>'
                    + "".join(f'<sheet name="{escape(name, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>'
                              for i, (name, _, _) in zip(n, sheets))
                    + "</sheets></workbook>")
        book_rels = (f'{_HEAD}<Relationships xmlns="{_PKG}/relationships">'
                     + "".join(f'<Relationship Id="rId{i}" Type="{_REL}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in n)
                     + f'<Relationship Id="rId{len(sheets) + 1}" Type="{_REL}/styles" Target="styles.xml"/>'
                     '</Relationships>')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", content_types)
            z.writestr("_rels/.rels", root_rels)
            z.writestr("xl/workbook.xml", workbook)
            z.writestr("xl/_rels/workbook.xml.rels", book_rels)
            z.writestr("xl/styles.xml", _STYLES)
            for i, (_, rows, widths) in zip(n, sheets):
                z.writestr(f"xl/worksheets/sheet{i}.xml", self._sheet_xml(rows, widths))
        return buf.getvalue()
