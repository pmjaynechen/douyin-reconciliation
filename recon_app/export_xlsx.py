import io
import re
import zipfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape


XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def build_xlsx(metadata, columns, rows):
    """Build a small, typed XLSX workbook without a third-party dependency."""
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", _content_types_xml())
            archive.writestr("_rels/.rels", _root_relationships_xml())
            archive.writestr("xl/workbook.xml", _workbook_xml())
            archive.writestr("xl/_rels/workbook.xml.rels", _workbook_relationships_xml())
            archive.writestr("xl/styles.xml", _styles_xml())
            archive.writestr(
                "xl/worksheets/sheet1.xml",
                _metadata_sheet_xml(metadata),
            )
            archive.writestr(
                "xl/worksheets/sheet2.xml",
                _result_sheet_xml(columns, rows),
            )
        return buffer.getvalue()


def _content_types_xml():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )


def _root_relationships_xml():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )


def _workbook_xml():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets>'
        '<sheet name="导出说明" sheetId="1" r:id="rId1"/>'
        '<sheet name="对账结果" sheetId="2" r:id="rId2"/>'
        '</sheets>'
        '</workbook>'
    )


def _workbook_relationships_xml():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>'
    )


def _styles_xml():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="3">'
        '<numFmt numFmtId="164" formatCode="#,##0.00;[Red]-#,##0.00"/>'
        '<numFmt numFmtId="165" formatCode="yyyy-mm-dd hh:mm:ss"/>'
        '<numFmt numFmtId="166" formatCode="0.########"/>'
        '</numFmts>'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Arial"/></font>'
        '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Arial"/></font>'
        '</fonts>'
        '<fills count="4">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF246BFD"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFEAF2FF"/><bgColor indexed="64"/></patternFill></fill>'
        '</fills>'
        '<borders count="2">'
        '<border><left/><right/><top/><bottom/><diagonal/></border>'
        '<border><left style="thin"><color rgb="FFDDE3EA"/></left><right style="thin"><color rgb="FFDDE3EA"/></right><top style="thin"><color rgb="FFDDE3EA"/></top><bottom style="thin"><color rgb="FFDDE3EA"/></bottom><diagonal/></border>'
        '</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="8">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>'
        '<xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
        '<xf numFmtId="166" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )


def _metadata_sheet_xml(metadata):
    rows = []
    for row_number, (label, value) in enumerate(metadata, 1):
        rows.append(
            '<row r="{0}">{1}{2}</row>'.format(
                row_number,
                _text_cell("A{}".format(row_number), label, 6),
                _text_cell("B{}".format(row_number), value, 7),
            )
        )
    last_row = max(1, len(rows))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<dimension ref="A1:B{}"/>'.format(last_row)
        + '<cols><col min="1" max="1" width="18" customWidth="1"/><col min="2" max="2" width="72" customWidth="1"/></cols>'
        + '<sheetData>{}</sheetData>'.format("".join(rows))
        + '<pageMargins left="0.3" right="0.3" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>'
        + '</worksheet>'
    )


def _result_sheet_xml(columns, rows):
    last_column = _column_name(max(0, len(columns) - 1))
    last_row = max(1, len(rows) + 1)
    column_xml = []
    header_cells = []
    for index, column in enumerate(columns):
        column_xml.append(
            '<col min="{0}" max="{0}" width="{1}" customWidth="1"/>'.format(
                index + 1, column.get("width", 16)
            )
        )
        header_cells.append(
            _text_cell("{}1".format(_column_name(index)), column["label"], 1)
        )
    sheet_rows = ['<row r="1" ht="24" customHeight="1">{}</row>'.format("".join(header_cells))]
    for row_number, values in enumerate(rows, 2):
        cells = []
        for index, column in enumerate(columns):
            reference = "{}{}".format(_column_name(index), row_number)
            value = values[index] if index < len(values) else None
            cells.append(_typed_cell(reference, value, column.get("kind", "text")))
        sheet_rows.append('<row r="{}">{}</row>'.format(row_number, "".join(cells)))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<dimension ref="A1:{0}{1}"/>'.format(last_column, last_row)
        + '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        + '<sheetFormatPr defaultRowHeight="18"/>'
        + '<cols>{}</cols>'.format("".join(column_xml))
        + '<sheetData>{}</sheetData>'.format("".join(sheet_rows))
        + '<autoFilter ref="A1:{0}{1}"/>'.format(last_column, last_row)
        + '<pageMargins left="0.3" right="0.3" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>'
        + '</worksheet>'
    )


def _typed_cell(reference, value, kind):
    if value is None or value == "":
        return '<c r="{}" s="{}"/>'.format(reference, _style_for_kind(kind))
    if kind == "money_cents":
        try:
            number = Decimal(str(value)) / Decimal("100")
        except (InvalidOperation, ValueError):
            return _text_cell(reference, value, 5)
        return _number_cell(reference, number, 2)
    if kind == "datetime":
        serial = _excel_datetime_serial(value)
        if serial is None:
            return _text_cell(reference, value, 5)
        return _number_cell(reference, serial, 3)
    if kind == "number":
        try:
            return _number_cell(reference, Decimal(str(value)), 4)
        except (InvalidOperation, ValueError):
            return _text_cell(reference, value, 5)
    return _text_cell(reference, value, 5)


def _style_for_kind(kind):
    return {"money_cents": 2, "datetime": 3, "number": 4}.get(kind, 5)


def _number_cell(reference, value, style):
    text = format(value, "f") if isinstance(value, Decimal) else str(value)
    return '<c r="{}" s="{}"><v>{}</v></c>'.format(reference, style, text)


def _text_cell(reference, value, style):
    cleaned = _clean_xml_text(value)
    preserve = ' xml:space="preserve"' if cleaned != cleaned.strip() else ""
    return '<c r="{}" s="{}" t="inlineStr"><is><t{}>{}</t></is></c>'.format(
        reference, style, preserve, escape(cleaned)
    )


def _excel_datetime_serial(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(raw, date_format)
                    break
                except ValueError:
                    parsed = None
            if parsed is None:
                return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    epoch = datetime(1899, 12, 30)
    delta = parsed - epoch
    return Decimal(delta.days) + (Decimal(delta.seconds) / Decimal(86400))


def _clean_xml_text(value):
    text = str(value)
    return re.sub(
        r"[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD]",
        "",
        text,
    )


def _column_name(index):
    value = index + 1
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result
