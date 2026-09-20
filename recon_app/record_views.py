import json
import math

from .data_import import normalize_identifier


SHEET_VIEWS = {
    "订单明细": {
        "amount_label": "订单应付金额合计",
        "columns": (
            ("excelRow", "Excel行", "integer", "row_number"),
            ("mainOrderId", "主订单编号", "identifier", "raw:主订单编号"),
            ("subOrderId", "子订单编号", "identifier", "primary_identifier"),
            ("sku", "货号", "text", "raw:货号"),
            ("quantity", "商品数量", "number", "raw:商品数量"),
            ("unitPrice", "商品金额", "money", "raw:商品金额"),
            ("shippingFee", "运费", "money", "raw:运费"),
            ("platformDiscount", "平台承担优惠", "money", "raw:平台实际承担优惠金额"),
            ("merchantDiscount", "商家承担优惠", "money", "raw:商家实际承担优惠金额"),
            ("creatorDiscount", "达人承担优惠", "money", "raw:达人实际承担优惠金额"),
            ("payableAmount", "订单应付金额", "cents", "amount_cents"),
            ("submittedAt", "订单提交时间", "datetime", "event_time"),
            ("orderStatus", "订单状态", "text", "raw:订单状态"),
            ("orderType", "订单类型", "text", "raw:订单类型"),
            ("afterSaleStatus", "售后状态", "text", "raw:售后状态"),
        ),
    },
    "售后表": {
        "amount_label": "退商品金额合计",
        "columns": (
            ("excelRow", "Excel行", "integer", "row_number"),
            ("afterSaleId", "售后单号", "identifier", "primary_identifier"),
            ("orderId", "订单号", "identifier", "raw:订单号"),
            ("itemOrderId", "商品单号", "identifier", "secondary_identifier"),
            ("afterSaleType", "售后类型", "text", "raw:售后类型"),
            ("afterSaleStatus", "售后状态", "text", "raw:售后状态"),
            ("appliedAt", "售后申请时间", "datetime", "event_time"),
            ("refundGoods", "退商品金额", "cents", "amount_cents"),
            ("refundShipping", "退运费金额", "money", "raw:退运费金额（元）"),
            ("refundMethod", "退款方式", "text", "raw:退款方式"),
        ),
    },
    "结算账单": {
        "amount_label": "结算金额合计",
        "columns": (
            ("excelRow", "Excel行", "integer", "row_number"),
            ("settledAt", "结算时间", "datetime", "event_time"),
            ("orderId", "订单号", "identifier", "secondary_identifier"),
            ("subOrderId", "子订单号", "identifier", "primary_identifier"),
            ("settlementType", "结算单类型", "text", "raw:结算单类型"),
            ("account", "结算账户", "text", "raw:结算账户"),
            ("orderTotal", "订单总价", "money", "raw:订单总价"),
            ("incomeTotal", "收入合计", "money", "raw:收入合计"),
            ("expenseTotal", "支出合计", "money", "raw:支出合计"),
            ("settlementAmount", "结算金额", "cents", "amount_cents"),
        ),
    },
    "资金账单": {
        "amount_label": "资金净变动",
        "columns": (
            ("excelRow", "Excel行", "integer", "row_number"),
            ("changedAt", "动账时间", "datetime", "event_time"),
            ("transactionId", "动账流水号", "identifier", "primary_identifier"),
            ("direction", "动账方向", "text", "raw:动账方向"),
            ("amount", "动账金额", "cents", "amount_cents"),
            ("account", "动账账户", "text", "raw:动账账户"),
            ("scene", "动账场景", "text", "raw:动账场景"),
            ("chargeType", "计费类型", "text", "raw:计费类型"),
            ("subOrderId", "子订单号", "identifier", "secondary_identifier"),
            ("afterSaleId", "售后编号", "identifier", "raw:售后编号"),
            ("remark", "备注", "text", "raw:备注"),
        ),
    },
    "成本表": {
        "amount_label": "成本价范围",
        "columns": (
            ("excelRow", "Excel行", "integer", "row_number"),
            ("model", "型号", "identifier", "primary_identifier"),
            ("costPrice", "成本价", "cents", "amount_cents"),
        ),
    },
}


def enrich_import_summary(connection, import_id, data_import, inspection):
    if not data_import or not import_id:
        return data_import

    aggregates = connection.execute(
        """
        SELECT sheet_name,
               COUNT(*) AS record_count,
               COALESCE(SUM(amount_cents), 0) AS amount_sum_cents,
               COALESCE(SUM(CASE WHEN amount_cents > 0 THEN amount_cents ELSE 0 END), 0)
                   AS inflow_cents,
               COALESCE(SUM(CASE WHEN amount_cents < 0 THEN -amount_cents ELSE 0 END), 0)
                   AS outflow_cents,
               MIN(amount_cents) AS amount_min_cents,
               MAX(amount_cents) AS amount_max_cents
        FROM source_records
        WHERE import_id = ?
        GROUP BY sheet_name
        """,
        (import_id,),
    ).fetchall()
    by_sheet = {row["sheet_name"]: dict(row) for row in aggregates}
    columns_by_sheet = {
        item["name"]: item.get("columnCount", 0)
        for item in inspection.get("sheets", [])
    }

    for summary in data_import.get("sheetSummaries", []):
        sheet_name = summary["name"]
        aggregate = by_sheet.get(sheet_name, {})
        summary["columnCount"] = columns_by_sheet.get(sheet_name, 0)
        summary["displayColumnCount"] = len(SHEET_VIEWS[sheet_name]["columns"])
        summary["amountSummary"] = _amount_summary(sheet_name, aggregate)

    issue_rows = connection.execute(
        """
        SELECT severity, code, sheet_name, field_name, raw_value
        FROM data_issues
        WHERE import_id = ? AND raw_value IS NOT NULL AND raw_value != ''
        ORDER BY id ASC
        """,
        (import_id,),
    ).fetchall()
    raw_values_by_group = {}
    for row in issue_rows:
        key = (row["severity"], row["code"], row["sheet_name"], row["field_name"])
        values = raw_values_by_group.setdefault(key, [])
        if row["raw_value"] not in values and len(values) < 5:
            values.append(row["raw_value"])
    for group in data_import.get("issueGroups", []):
        key = (
            group.get("severity"),
            group.get("code"),
            group.get("sheetName"),
            group.get("fieldName"),
        )
        group["rawValues"] = raw_values_by_group.get(key, group.get("rawValues", []))
    return data_import


def build_record_page(connection, import_id, file_id, sheet_name, page, page_size):
    view = SHEET_VIEWS[sheet_name]
    total = connection.execute(
        "SELECT COUNT(*) AS count FROM source_records WHERE import_id = ? AND sheet_name = ?",
        (import_id, sheet_name),
    ).fetchone()["count"]
    total_pages = max(1, int(math.ceil(total / float(page_size))))
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * page_size
    records = connection.execute(
        """
        SELECT id, row_number, primary_identifier, secondary_identifier,
               event_time, amount_cents, raw_values_json
        FROM source_records
        WHERE import_id = ? AND sheet_name = ?
        ORDER BY row_number ASC, id ASC
        LIMIT ? OFFSET ?
        """,
        (import_id, sheet_name, page_size, offset),
    ).fetchall()

    rows = []
    for record in records:
        raw_values = json.loads(record["raw_values_json"])
        values = {}
        for key, _label, value_type, source in view["columns"]:
            values[key] = _value_from_record(record, raw_values, value_type, source)
        rows.append(
            {
                "id": record["id"],
                "excelRow": record["row_number"],
                "values": values,
            }
        )

    return {
        "fileId": file_id,
        "sheetName": sheet_name,
        "columns": [
            {"key": key, "label": label, "type": value_type}
            for key, label, value_type, _source in view["columns"]
        ],
        "rows": rows,
        "pagination": {
            "page": page,
            "pageSize": page_size,
            "totalRows": total,
            "totalPages": total_pages,
            "fromRow": offset + 1 if total else 0,
            "toRow": min(offset + page_size, total),
        },
    }


def _amount_summary(sheet_name, aggregate):
    view = SHEET_VIEWS[sheet_name]
    result = {
        "label": view["amount_label"],
        "valueCents": aggregate.get("amount_sum_cents", 0),
    }
    if sheet_name == "资金账单":
        result["inflowCents"] = aggregate.get("inflow_cents", 0)
        result["outflowCents"] = aggregate.get("outflow_cents", 0)
    if sheet_name == "成本表":
        result["minCents"] = aggregate.get("amount_min_cents")
        result["maxCents"] = aggregate.get("amount_max_cents")
    return result


def _value_from_record(record, raw_values, value_type, source):
    if source.startswith("raw:"):
        value = raw_values.get(source[4:])
    else:
        value = record[source]
    if value_type == "identifier":
        return normalize_identifier(value) or None
    return value
