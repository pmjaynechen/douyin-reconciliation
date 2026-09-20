import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .xlsx import extract_workbook_rows


SHEET_RULES = {
    "订单明细": {
        "record_type": "order",
        "primary": "子订单编号",
        "secondary": "主订单编号",
        "date": "订单提交时间",
        "amount": "订单应付金额",
        "required_text": ("子订单编号", "订单状态", "订单类型"),
        "required_numbers": ("商品数量", "商品金额", "订单应付金额", "运费"),
        "duplicate_key": ("子订单编号",),
        "stored_fields": (
            "主订单编号", "子订单编号", "货号", "商品数量", "商品金额",
            "订单应付金额", "运费", "订单提交时间", "支付完成时间", "订单完成时间",
            "订单状态", "取消原因", "订单类型", "售后状态",
            "平台实际承担优惠金额", "商家实际承担优惠金额", "达人实际承担优惠金额",
        ),
    },
    "售后表": {
        "record_type": "after_sale",
        "primary": "售后单号",
        "secondary": "商品单号",
        "date": "售后申请时间",
        "amount": "退商品金额（元）",
        "required_text": ("售后单号", "订单号", "商品单号", "售后类型", "售后状态"),
        "required_numbers": (),
        "duplicate_key": ("售后单号",),
        "stored_fields": (
            "售后单号", "订单号", "商品单号", "售后类型", "售后状态",
            "售后申请时间", "退商品金额（元）", "退运费金额（元）", "退款方式", "申请原因",
        ),
    },
    "结算账单": {
        "record_type": "settlement",
        "primary": "子订单号",
        "secondary": "订单号",
        "date": "结算时间",
        "amount": "结算金额",
        "required_text": ("子订单号", "结算账户", "结算单类型"),
        "required_numbers": ("结算金额",),
        "duplicate_key": ("子订单号", "结算单类型"),
        "stored_fields": None,
    },
    "资金账单": {
        "record_type": "fund",
        "primary": "动帐流水号",
        "secondary": "子订单号",
        "date": "动账时间",
        "amount": "动账金额",
        "required_text": ("动帐流水号", "动账方向", "动账账户"),
        "required_numbers": ("动账金额",),
        "duplicate_key": ("动帐流水号",),
        "stored_fields": None,
    },
    "成本表": {
        "record_type": "cost",
        "primary": "型号",
        "secondary": None,
        "date": None,
        "amount": "成本价",
        "required_text": ("型号",),
        "required_numbers": ("成本价",),
        "duplicate_key": ("型号",),
        "stored_fields": None,
    },
}


def analyze_workbook_data(file_path, task_period, workbook_definitions=None):
    workbook_rows = extract_workbook_rows(file_path, workbook_definitions)
    records = []
    issues = []
    sheet_summaries = []
    records_by_sheet = defaultdict(list)

    for sheet_name, rule in SHEET_RULES.items():
        source_rows = workbook_rows.get(sheet_name, [])
        for source_row in source_rows:
            record, row_issues = _build_record(sheet_name, source_row, rule)
            records.append(record)
            records_by_sheet[sheet_name].append(record)
            issues.extend(row_issues)

        duplicate_groups = _find_duplicates(source_rows, rule["duplicate_key"])
        for key, rows in duplicate_groups.items():
            for source_row in rows:
                issues.append(
                    _issue(
                        "blocking",
                        "duplicate_identifier",
                        sheet_name,
                        source_row["rowNumber"],
                        "＋".join(rule["duplicate_key"]),
                        " / ".join(key),
                        "编号重复，不能自动判断",
                        "返回Excel确认重复行应保留、修改还是删除",
                    )
                )

    _append_business_warnings(records_by_sheet, issues, task_period)

    issue_counter = Counter((item["sheetName"], item["severity"]) for item in issues)
    for sheet_name, rule in SHEET_RULES.items():
        rows = records_by_sheet.get(sheet_name, [])
        dates = sorted(item["eventTime"] for item in rows if item["eventTime"])
        sheet_summaries.append(
            {
                "name": sheet_name,
                "recordType": rule["record_type"],
                "recordCount": len(rows),
                "blockingIssueCount": issue_counter[(sheet_name, "blocking")],
                "warningIssueCount": issue_counter[(sheet_name, "warning")],
                "dateFrom": dates[0][:10] if dates else None,
                "dateTo": dates[-1][:10] if dates else None,
            }
        )

    blocking_count = sum(1 for item in issues if item["severity"] == "blocking")
    warning_count = sum(1 for item in issues if item["severity"] == "warning")
    status = "failed" if blocking_count else "warning" if warning_count else "passed"
    return {
        "status": status,
        "totalRecordCount": len(records),
        "blockingIssueCount": blocking_count,
        "warningIssueCount": warning_count,
        "sheetSummaries": sheet_summaries,
        "issueGroups": _group_issues(issues),
        "issuePreview": issues[:100],
        "records": records,
        "issues": issues,
    }


def _build_record(sheet_name, source_row, rule):
    values = source_row["values"]
    row_number = source_row["rowNumber"]
    issues = []

    for field_name in rule["required_text"]:
        if not normalize_text(values.get(field_name)):
            issues.append(
                _issue(
                    "blocking",
                    "missing_required_value",
                    sheet_name,
                    row_number,
                    field_name,
                    values.get(field_name),
                    "必要字段为空",
                    "在Excel中补充后重新导入",
                )
            )

    normalized_numbers = {}
    for field_name in rule["required_numbers"]:
        raw_value = values.get(field_name)
        cents, error = parse_money_or_number(raw_value, cents=field_name not in ("商品数量",))
        normalized_numbers[field_name] = cents
        if error:
            issues.append(
                _issue(
                    "blocking",
                    "invalid_number",
                    sheet_name,
                    row_number,
                    field_name,
                    raw_value,
                    error,
                    "改成可计算数字后重新导入",
                )
            )

    primary_identifier = normalize_identifier(values.get(rule["primary"]))
    secondary_identifier = normalize_identifier(values.get(rule["secondary"])) if rule["secondary"] else None
    if primary_identifier and re.search(r"[eE][+-]?\d+$", primary_identifier):
        issues.append(
            _issue(
                "blocking",
                "identifier_precision_risk",
                sheet_name,
                row_number,
                rule["primary"],
                values.get(rule["primary"]),
                "编号显示为科学计数法，可能已经丢失精度",
                "把Excel编号列改成文本并重新导出",
            )
        )

    event_time = None
    if rule["date"]:
        event_time, date_error = parse_excel_datetime(values.get(rule["date"]))
        if date_error:
            issues.append(
                _issue(
                    "blocking",
                    "invalid_date",
                    sheet_name,
                    row_number,
                    rule["date"],
                    values.get(rule["date"]),
                    date_error,
                    "改成有效日期时间后重新导入",
                )
            )

    amount_cents = None
    if rule["amount"]:
        amount_cents, amount_error = parse_money_or_number(values.get(rule["amount"]), cents=True)
        if amount_error and rule["amount"] not in rule["required_numbers"]:
            issues.append(
                _issue(
                    "warning",
                    "invalid_optional_amount",
                    sheet_name,
                    row_number,
                    rule["amount"],
                    values.get(rule["amount"]),
                    amount_error,
                    "核实金额格式；该字段暂不参与自动判断",
                )
            )
    if sheet_name == "资金账单" and amount_cents is not None:
        direction = normalize_text(values.get("动账方向"))
        if direction == "出账":
            amount_cents = -abs(amount_cents)
        elif direction == "入账":
            amount_cents = abs(amount_cents)
        elif direction:
            issues.append(
                _issue(
                    "blocking",
                    "invalid_direction",
                    sheet_name,
                    row_number,
                    "动账方向",
                    values.get("动账方向"),
                    "动账方向不是入账或出账",
                    "核实平台源字段后重新导入",
                )
            )

    if sheet_name == "订单明细" and not normalize_identifier(values.get("货号")):
        issues.append(
            _issue(
                "warning",
                "missing_sku",
                sheet_name,
                row_number,
                "货号",
                values.get("货号"),
                "缺少货号，后续无法关联成本",
                "补充货号，或在结果中保留为缺少资料",
            )
        )

    if sheet_name == "资金账单" and not normalize_text(values.get("动账场景")):
        issues.append(
            _issue(
                "warning",
                "missing_fund_scene",
                sheet_name,
                row_number,
                "动账场景",
                values.get("动账场景"),
                "动账场景为空，不能直接归入普通结算",
                "结合计费类型和备注进行分类",
            )
        )

    return (
        {
            "sheetName": sheet_name,
            "rowNumber": row_number,
            "recordType": rule["record_type"],
            "primaryIdentifier": primary_identifier,
            "secondaryIdentifier": secondary_identifier,
            "eventTime": event_time,
            "amountCents": amount_cents,
            "rawValuesJson": json.dumps(
                _stored_values(values, rule["stored_fields"]),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
        issues,
    )


def _find_duplicates(source_rows, fields):
    grouped = defaultdict(list)
    for source_row in source_rows:
        key = tuple(normalize_identifier(source_row["values"].get(field)) for field in fields)
        if all(key):
            grouped[key].append(source_row)
    return {key: rows for key, rows in grouped.items() if len(rows) > 1}


def _append_business_warnings(records_by_sheet, issues, task_period):
    order_records = records_by_sheet.get("订单明细", [])
    order_months = sorted(set(item["eventTime"][:7] for item in order_records if item["eventTime"]))
    if order_months and task_period not in order_months:
        issues.append(
            _issue(
                "blocking",
                "task_period_mismatch",
                "订单明细",
                None,
                "订单提交时间",
                "、".join(order_months),
                "订单文件月份与任务月份{}不一致".format(task_period),
                "选择正确月份的任务，或导入对应月份文件",
            )
        )
    elif len(order_months) > 1:
        issues.append(
            _issue(
                "blocking",
                "mixed_task_periods",
                "订单明细",
                None,
                "订单提交时间",
                "、".join(order_months),
                "订单文件同时包含多个下单月份，不能确认本期数据边界",
                "按任务月份重新导出订单明细；跨月结算订单由历史任务自动关联",
            )
        )

    issues.append(
        _issue(
            "warning",
            "cost_effective_date_missing",
            "成本表",
            None,
            "成本生效日期",
            None,
            "当前成本表没有生效日期，只能按静态成本使用",
            "正式使用真实成本前补充开始日期和结束日期",
        )
    )


def _stored_values(values, stored_fields):
    if stored_fields is None:
        return values
    return {field: values[field] for field in stored_fields if field in values}


def _group_issues(issues):
    groups = {}
    for item in issues:
        key = (
            item["severity"],
            item["code"],
            item["sheetName"],
            item["fieldName"],
            item["message"],
            item["suggestion"],
        )
        if key not in groups:
            groups[key] = {
                "severity": item["severity"],
                "code": item["code"],
                "sheetName": item["sheetName"],
                "fieldName": item["fieldName"],
                "message": item["message"],
                "suggestion": item["suggestion"],
                "count": 0,
                "exampleRows": [],
                "rawValues": [],
            }
        group = groups[key]
        group["count"] += 1
        if item["rowNumber"] is not None and len(group["exampleRows"]) < 5:
            group["exampleRows"].append(item["rowNumber"])
        raw_value = item.get("rawValue")
        if raw_value not in (None, "") and raw_value not in group["rawValues"]:
            if len(group["rawValues"]) < 5:
                group["rawValues"].append(raw_value)
    return list(groups.values())


def parse_excel_datetime(value):
    cleaned = normalize_text(value)
    if not cleaned:
        return None, "日期为空"
    try:
        serial = Decimal(cleaned)
        if not serial.is_finite():
            raise InvalidOperation
        parsed = datetime(1899, 12, 30) + timedelta(days=float(serial))
        if parsed.year < 2000 or parsed.year > 2100:
            return None, "日期超出2000—2100的合理范围"
        return parsed.replace(microsecond=0).isoformat(), None
    except (InvalidOperation, ValueError, OverflowError):
        pass

    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(cleaned, pattern).isoformat(), None
        except ValueError:
            continue
    return None, "日期格式无法识别"


def parse_money_or_number(value, cents=True):
    cleaned = normalize_text(value)
    if not cleaned:
        return None, "数值为空"
    cleaned = cleaned.replace(",", "").replace("￥", "").replace("¥", "")
    try:
        number = Decimal(cleaned)
        if not number.is_finite():
            raise InvalidOperation
    except InvalidOperation:
        return None, "不是有效数字"
    if cents:
        return int((number * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)), None
    if number != number.to_integral_value():
        return None, "商品数量必须是整数"
    return int(number), None


def normalize_text(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_identifier(value):
    cleaned = normalize_text(value)
    while cleaned.startswith("'"):
        cleaned = cleaned[1:]
    return cleaned.strip()


def _issue(severity, code, sheet_name, row_number, field_name, raw_value, message, suggestion):
    if raw_value is None:
        safe_value = None
    else:
        safe_value = str(raw_value)[:500]
    return {
        "severity": severity,
        "code": code,
        "sheetName": sheet_name,
        "rowNumber": row_number,
        "fieldName": field_name,
        "rawValue": safe_value,
        "message": message,
        "suggestion": suggestion,
    }
