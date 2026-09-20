import io
import posixpath
import re
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree


MAX_ARCHIVE_ENTRIES = 5000
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_SINGLE_ENTRY_BYTES = 100 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


REQUIRED_SHEETS = (
    {
        "name": "订单明细",
        "header_row": 1,
        "data_start_row": 2,
        "baseline_rows": 2435,
        "baseline_columns": 75,
        "required_headers": (
            "子订单编号",
            "货号",
            "商品数量",
            "商品金额",
            "订单提交时间",
            "订单完成时间",
            "订单应付金额",
        ),
    },
    {
        "name": "售后表",
        "header_row": 1,
        "data_start_row": 2,
        "baseline_rows": 212,
        "baseline_columns": 50,
        "required_headers": (
            "售后单号",
            "订单号",
            "商品单号",
            "售后类型",
            "售后状态",
            "售后申请时间",
        ),
    },
    {
        "name": "结算账单",
        "header_row": 1,
        "data_start_row": 3,
        "baseline_rows": 381,
        "baseline_columns": 34,
        "required_headers": (
            "结算时间",
            "订单号",
            "子订单号",
            "结算金额",
            "结算账户",
            "结算单类型",
        ),
    },
    {
        "name": "资金账单",
        "header_row": 1,
        "data_start_row": 2,
        "baseline_rows": 655,
        "baseline_columns": 30,
        "required_headers": (
            "动账时间",
            "动帐流水号",
            "动账方向",
            "动账金额",
            "动账账户",
            "动账场景",
            "子订单号",
        ),
    },
    {
        "name": "成本表",
        "header_row": 1,
        "data_start_row": 2,
        "baseline_rows": 11,
        "baseline_columns": 2,
        "required_headers": ("型号", "成本价"),
    },
)


def extract_workbook_rows(file_path, definitions=None):
    """Return every non-empty business row with original values and source location."""
    try:
        archive = zipfile.ZipFile(str(file_path), "r")
    except (OSError, zipfile.BadZipFile):
        raise WorkbookInspectionError("文件不是有效的.xlsx工作簿")

    with archive:
        _validate_archive(archive)
        shared_strings = _read_shared_strings(archive)
        workbook_root = _read_xml(archive, "xl/workbook.xml")
        relationships = _read_relationships(archive)
        sheet_paths = _read_sheet_paths(workbook_root, relationships)
        result = {}
        for definition in definitions or REQUIRED_SHEETS:
            matches = _matching_sheet_paths(sheet_paths, definition)
            if not matches:
                continue
            if len(matches) > 1:
                raise WorkbookInspectionError(
                    "{}同时匹配多个工作表：{}".format(
                        definition["name"], "、".join(item[0] for item in matches)
                    )
                )
            _, sheet_path = matches[0]
            result[definition["name"]] = _extract_sheet_rows(
                archive, sheet_path, definition, shared_strings
            )
        return result


def extract_defined_workbook_rows(file_path, definitions):
    """Extract business rows for a caller-supplied set of worksheet definitions."""
    try:
        archive = zipfile.ZipFile(str(file_path), "r")
    except (OSError, zipfile.BadZipFile):
        raise WorkbookInspectionError("文件不是有效的.xlsx工作簿")

    with archive:
        _validate_archive(archive)
        shared_strings = _read_shared_strings(archive)
        workbook_root = _read_xml(archive, "xl/workbook.xml")
        relationships = _read_relationships(archive)
        sheet_paths = _read_sheet_paths(workbook_root, relationships)
        result = {}
        for definition in definitions:
            matches = _matching_sheet_paths(sheet_paths, definition)
            if not matches:
                continue
            if len(matches) > 1:
                raise WorkbookInspectionError(
                    "{}同时匹配多个工作表：{}".format(
                        definition["name"], "、".join(item[0] for item in matches)
                    )
                )
            _, sheet_path = matches[0]
            result[definition["name"]] = _extract_sheet_rows(
                archive, sheet_path, definition, shared_strings
            )
        return result


def inspect_defined_workbook(file_path, definitions):
    """Inspect a supporting workbook without changing the five-sheet core contract."""
    return _inspect_with_definitions(file_path, definitions)


class WorkbookInspectionError(Exception):
    pass


def inspect_workbook(file_path, definitions=None):
    return _inspect_with_definitions(file_path, definitions or REQUIRED_SHEETS)


def _inspect_with_definitions(file_path, definitions):
    try:
        archive = zipfile.ZipFile(str(file_path), "r")
    except (OSError, zipfile.BadZipFile):
        raise WorkbookInspectionError("文件不是有效的.xlsx工作簿")

    with archive:
        _validate_archive(archive)
        names = set(archive.namelist())
        for required_name in (
            "[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"
        ):
            if required_name not in names:
                raise WorkbookInspectionError("文件缺少Excel工作簿必要结构")
        shared_strings = _read_shared_strings(archive)
        workbook_root = _read_xml(archive, "xl/workbook.xml")
        relationships = _read_relationships(archive)
        sheet_paths = _read_sheet_paths(workbook_root, relationships)
        sheet_results = []
        errors = []
        warnings = []
        for definition in definitions:
            name = definition["name"]
            matches = [item for item in _matching_sheet_paths(sheet_paths, definition) if item[1] in names]
            if not matches:
                message = "缺少工作表：{}".format(name)
                errors.append(message)
                sheet_results.append({
                    "name": name,
                    "present": False,
                    "status": "missing",
                    "headerRow": definition["header_row"],
                    "dataStartRow": definition["data_start_row"],
                    "dataRowCount": 0,
                    "columnCount": 0,
                    "headers": [],
                    "missingRequiredHeaders": list(definition["required_headers"]),
                    "warnings": [message],
                })
                continue
            if len(matches) > 1:
                message = "{}同时匹配多个工作表：{}".format(
                    name, "、".join(item[0] for item in matches)
                )
                errors.append(message)
                sheet_results.append({
                    "name": name,
                    "present": True,
                    "status": "failed",
                    "headerRow": definition["header_row"],
                    "dataStartRow": definition["data_start_row"],
                    "dataRowCount": 0,
                    "columnCount": 0,
                    "headers": [],
                    "missingRequiredHeaders": [],
                    "ambiguousFieldMappings": [],
                    "warnings": [message],
                })
                continue
            source_name, sheet_path = matches[0]
            result = _inspect_sheet(
                archive, sheet_path, definition, shared_strings, source_name
            )
            sheet_results.append(result)
            if result["missingRequiredHeaders"]:
                errors.append("{}缺少必要字段：{}".format(
                    name, "、".join(result["missingRequiredHeaders"])
                ))
            if result["dataRowCount"] == 0:
                errors.append("{}没有可用数据".format(name))
            if result.get("ambiguousFieldMappings"):
                errors.extend(
                    "{}字段{}同时匹配：{}".format(
                        name, item["fieldName"], "、".join(item["sourceHeaders"])
                    )
                    for item in result["ambiguousFieldMappings"]
                )
            warnings.extend("{}：{}".format(name, item) for item in result["warnings"])
        return {
            "status": "passed" if not errors else "failed",
            "sheetCount": len(sheet_paths),
            "requiredSheetCount": len(definitions),
            "foundRequiredSheetCount": sum(item["present"] for item in sheet_results),
            "sheets": sheet_results,
            "errors": errors,
            "warnings": warnings,
        }


def _validate_archive(archive):
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        raise WorkbookInspectionError("工作簿内部文件数量异常")

    total_size = 0
    for entry in entries:
        path = PurePosixPath(entry.filename)
        if entry.filename.startswith("/") or ".." in path.parts:
            raise WorkbookInspectionError("工作簿包含不安全的文件路径")
        if entry.flag_bits & 0x1:
            raise WorkbookInspectionError("暂不支持加密工作簿")
        if entry.file_size > MAX_SINGLE_ENTRY_BYTES:
            raise WorkbookInspectionError("工作簿内部单个文件过大")
        total_size += entry.file_size
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise WorkbookInspectionError("工作簿解压后体积过大")
        if (
            entry.file_size > 1024 * 1024
            and entry.compress_size > 0
            and entry.file_size / entry.compress_size > MAX_COMPRESSION_RATIO
        ):
            raise WorkbookInspectionError("工作簿压缩比例异常")


def _read_shared_strings(archive):
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = _read_xml(archive, "xl/sharedStrings.xml")
    strings = []
    for item in root.findall("{{{}}}si".format(MAIN_NS)):
        value = "".join(node.text or "" for node in item.iter("{{{}}}t".format(MAIN_NS)))
        strings.append(value)
    return strings


def _read_relationships(archive):
    root = _read_xml(archive, "xl/_rels/workbook.xml.rels")
    relationships = {}
    for item in root.findall("{{{}}}Relationship".format(PACKAGE_REL_NS)):
        relationship_id = item.attrib.get("Id")
        target = item.attrib.get("Target")
        if relationship_id and target:
            clean_target = target.lstrip("/")
            normalized = posixpath.normpath(
                clean_target if clean_target.startswith("xl/")
                else posixpath.join("xl", clean_target)
            )
            if normalized.startswith("../"):
                raise WorkbookInspectionError("工作簿关系路径不安全")
            relationships[relationship_id] = normalized
    return relationships


def _read_sheet_paths(workbook_root, relationships):
    result = {}
    sheets = workbook_root.find("{{{}}}sheets".format(MAIN_NS))
    if sheets is None:
        raise WorkbookInspectionError("工作簿没有工作表")
    relationship_key = "{{{}}}id".format(DOC_REL_NS)
    for sheet in sheets.findall("{{{}}}sheet".format(MAIN_NS)):
        name = sheet.attrib.get("name")
        relationship_id = sheet.attrib.get(relationship_key)
        if name and relationship_id in relationships:
            result[name] = relationships[relationship_id]
    return result


def _matching_sheet_paths(sheet_paths, definition):
    candidates = []
    for candidate in (
        definition.get("source_name"),
        definition.get("name"),
        *(definition.get("sheet_aliases") or ()),
    ):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return [(name, sheet_paths[name]) for name in candidates if name in sheet_paths]


def _field_sources(definition, canonical_name):
    aliases = (definition.get("field_aliases") or {}).get(canonical_name) or ()
    result = []
    for name in (canonical_name, *aliases):
        if name and name not in result:
            result.append(name)
    return result


def _inspect_sheet(archive, sheet_path, definition, shared_strings, source_name=None):
    raw = _read_xml_bytes(archive, sheet_path)
    header_values = {}
    data_row_count = 0
    last_data_row = None
    note = None

    for row in _iter_rows(raw):
        row_number = _safe_int(row.attrib.get("r"))
        values = {}
        for cell in row.findall("{{{}}}c".format(MAIN_NS)):
            reference = cell.attrib.get("r", "")
            column_index = _column_index(reference)
            value = _cell_value(cell, shared_strings)
            if column_index is not None and value not in (None, ""):
                values[column_index] = value

        if row_number == definition["header_row"]:
            header_values = values
        if definition["name"] == "结算账单" and row_number == 2 and values:
            note_items = [str(values[index]).strip() for index in sorted(values)]
            note = "；".join(item for item in note_items if item)[:500]
        if row_number is not None and row_number >= definition["data_start_row"] and values:
            data_row_count += 1
            last_data_row = row_number
        row.clear()

    column_count = max(header_values.keys()) + 1 if header_values else 0
    headers = [str(header_values.get(index, "")).strip() for index in range(column_count)]
    available = set(item for item in headers if item)
    missing_headers = []
    ambiguous_mappings = []
    resolved_mappings = {}
    for canonical_name in definition["required_headers"]:
        matches = [
            item for item in _field_sources(definition, canonical_name)
            if item in available
        ]
        if not matches:
            missing_headers.append(canonical_name)
        elif len(matches) > 1:
            ambiguous_mappings.append({
                "fieldName": canonical_name,
                "sourceHeaders": matches,
            })
        else:
            resolved_mappings[canonical_name] = matches[0]
    sheet_warnings = []
    baseline_columns = definition.get("baseline_columns")
    baseline_rows = definition.get("baseline_rows")
    if baseline_columns is not None and column_count != baseline_columns:
        sheet_warnings.append(
            "当前{}列，练习基准为{}列".format(column_count, baseline_columns)
        )
    if baseline_rows is not None and data_row_count != baseline_rows:
        sheet_warnings.append(
            "当前{}条数据，练习基准为{}条；业务文件行数可以不同".format(
                data_row_count, baseline_rows
            )
        )

    status = "passed"
    if missing_headers or ambiguous_mappings or data_row_count == 0:
        status = "failed"
    elif sheet_warnings:
        status = "warning"

    return {
        "name": definition["name"],
        "sourceName": source_name or definition.get("source_name") or definition["name"],
        "present": True,
        "status": status,
        "headerRow": definition["header_row"],
        "dataStartRow": definition["data_start_row"],
        "dataRowCount": data_row_count,
        "lastDataRow": last_data_row,
        "columnCount": column_count,
        "baselineDataRowCount": baseline_rows,
        "baselineColumnCount": baseline_columns,
        "headers": headers,
        "missingRequiredHeaders": missing_headers,
        "ambiguousFieldMappings": ambiguous_mappings,
        "resolvedRequiredFieldMappings": resolved_mappings,
        "note": note,
        "warnings": sheet_warnings,
    }


def _extract_sheet_rows(archive, sheet_path, definition, shared_strings):
    raw = _read_xml_bytes(archive, sheet_path)
    headers_by_column = {}
    canonical_by_source = {}
    configured_fields = set(definition.get("configured_headers") or ())
    configured_fields.update(definition.get("required_headers") or ())
    configured_fields.update((definition.get("field_aliases") or {}).keys())
    for canonical_name in configured_fields:
        for source_name in _field_sources(definition, canonical_name):
            existing = canonical_by_source.get(source_name)
            if existing and existing != canonical_name:
                raise WorkbookInspectionError(
                    "模板字段{}同时映射到{}和{}".format(
                        source_name, existing, canonical_name
                    )
                )
            canonical_by_source[source_name] = canonical_name
    result = []
    for row in _iter_rows(raw):
        row_number = _safe_int(row.attrib.get("r"))
        values = _row_values(row, shared_strings)
        if row_number == definition["header_row"]:
            headers_by_column = {
                index: str(value).strip()
                for index, value in values.items()
                if value not in (None, "")
            }
        elif row_number is not None and row_number >= definition["data_start_row"] and values:
            mapped = {}
            for index, value in values.items():
                header = headers_by_column.get(index)
                if header:
                    mapped[canonical_by_source.get(header, header)] = value
            if mapped:
                result.append({"rowNumber": row_number, "values": mapped})
        row.clear()
    return result


def _row_values(row, shared_strings):
    values = {}
    for cell in row.findall("{{{}}}c".format(MAIN_NS)):
        reference = cell.attrib.get("r", "")
        column_index = _column_index(reference)
        value = _cell_value(cell, shared_strings)
        if column_index is not None and value not in (None, ""):
            values[column_index] = value
    return values


def _read_xml(archive, name):
    try:
        return ElementTree.fromstring(_read_xml_bytes(archive, name))
    except ElementTree.ParseError:
        raise WorkbookInspectionError("工作簿内部XML结构损坏")


def _read_xml_bytes(archive, name):
    try:
        raw = archive.read(name)
    except (KeyError, OSError, RuntimeError, zipfile.BadZipFile):
        raise WorkbookInspectionError("工作簿内部文件读取失败")
    prefix = raw[:4096].upper()
    if b"<!DOCTYPE" in prefix or b"<!ENTITY" in prefix:
        raise WorkbookInspectionError("工作簿包含不安全的XML声明")
    return raw


def _iter_rows(raw):
    try:
        for event, row in ElementTree.iterparse(io.BytesIO(raw), events=("end",)):
            if row.tag == "{{{}}}row".format(MAIN_NS):
                yield row
    except ElementTree.ParseError:
        raise WorkbookInspectionError("工作簿内部XML结构损坏")


def _cell_value(cell, shared_strings):
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter("{{{}}}t".format(MAIN_NS)))
    value_node = cell.find("{{{}}}v".format(MAIN_NS))
    if value_node is None or value_node.text is None:
        return None
    raw_value = value_node.text
    if cell_type == "s":
        index = _safe_int(raw_value)
        if index is None or index < 0 or index >= len(shared_strings):
            return None
        return shared_strings[index]
    if cell_type == "b":
        return raw_value == "1"
    return raw_value


def _column_index(reference):
    match = re.match(r"([A-Za-z]+)", reference or "")
    if not match:
        return None
    value = 0
    for character in match.group(1).upper():
        value = value * 26 + ord(character) - ord("A") + 1
    return value - 1


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
