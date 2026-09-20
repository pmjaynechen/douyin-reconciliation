from .data_import import normalize_identifier, normalize_text, parse_money_or_number
from .xlsx import (
    WorkbookInspectionError,
    extract_defined_workbook_rows,
    inspect_defined_workbook,
)


SIMULATION_MARKER = "SIMULATED_FOR_PRODUCT_VALIDATION"
MAPPING_VERSION = "SIM-V1.0"

MARKER_DEFINITION = {
    "name": "使用说明",
    "header_row": 5,
    "data_start_row": 6,
    "required_headers": ("数据标识", "模拟任务编号", "模拟月份", "模拟店铺"),
}

EVIDENCE_DEFINITIONS = {
    "erp_cost": {
        "sheet": {
            "name": "ERP成本退货",
            "header_row": 1,
            "data_start_row": 2,
            "required_headers": (
                "子订单号", "SKU", "出库日期", "出库数量", "单位成本（元）",
                "退货入库日期", "退货入库数量", "退货单位成本（元）", "数据说明",
            ),
        },
        "label": "ERP历史成本与退货入库",
    },
    "fulfillment_expense": {
        "sheet": {
            "name": "快递仓储费用",
            "header_row": 1,
            "data_start_row": 2,
            "required_headers": (
                "子订单号", "运单号", "费用日期", "快递费（元）", "仓储费（元）",
                "其他履约费（元）", "费用状态", "数据说明",
            ),
        },
        "label": "快递与仓储费用",
    },
    "operating_expense": {
        "sheet": {
            "name": "经营费用",
            "header_row": 1,
            "data_start_row": 2,
            "required_headers": (
                "费用日期", "费用类别", "金额（元）", "归属店铺", "分摊方式",
                "原始单号", "是否计入本期", "数据说明",
            ),
        },
        "label": "投流、线下及管理费用",
    },
}


def calculate_simulated_operating_evidence(
    file_path, evidence_type, task_id, task_period, task_store_name,
    valid_suborder_ids, is_sample,
):
    """Parse only the explicitly marked simulation workbook; other files remain unmapped."""
    definition = EVIDENCE_DEFINITIONS[evidence_type]
    marker_rows = extract_defined_workbook_rows(file_path, (MARKER_DEFINITION,)).get(
        MARKER_DEFINITION["name"], []
    )
    marker = marker_rows[0]["values"] if marker_rows else None
    if not marker or normalize_text(marker.get("数据标识")) != SIMULATION_MARKER:
        return None
    if not is_sample:
        raise WorkbookInspectionError("模拟经营资料只能用于样例任务，不能导入真实店铺")
    if normalize_text(marker.get("模拟任务编号")) != task_id:
        raise WorkbookInspectionError("模拟资料与当前样例任务不匹配")
    if normalize_text(marker.get("模拟月份")) != task_period:
        raise WorkbookInspectionError("模拟资料月份与当前任务不一致")
    if normalize_text(marker.get("模拟店铺")) != task_store_name:
        raise WorkbookInspectionError("模拟资料店铺与当前任务不一致")

    inspection = inspect_defined_workbook(file_path, (MARKER_DEFINITION, definition["sheet"]))
    if inspection["status"] != "passed":
        raise WorkbookInspectionError("；".join(inspection["errors"]))
    source_rows = extract_defined_workbook_rows(
        file_path, (definition["sheet"],)
    ).get(definition["sheet"]["name"], [])
    valid_ids = {normalize_identifier(value) for value in valid_suborder_ids if value}
    if evidence_type == "erp_cost":
        result = _calculate_erp_rows(source_rows, valid_ids)
    elif evidence_type == "fulfillment_expense":
        result = _calculate_fulfillment_rows(source_rows, valid_ids)
    else:
        result = _calculate_operating_expense_rows(source_rows, task_store_name)
    result.update({
        "mappingVersion": MAPPING_VERSION,
        "dataMode": "simulated_trial",
        "isSimulated": True,
        "evidenceType": evidence_type,
        "sheetName": definition["sheet"]["name"],
        "inspection": inspection,
    })
    return result


def _calculate_erp_rows(source_rows, valid_ids):
    rows = []
    seen = set()
    outbound_total = 0
    reversal_total = 0
    for source in source_rows:
        values = source["values"]
        identifier = normalize_identifier(values.get("子订单号"))
        problems = []
        outbound_qty, error = parse_money_or_number(values.get("出库数量"), cents=False)
        if error or outbound_qty is None or outbound_qty <= 0:
            problems.append("出库数量必须为正整数")
        unit_cost, error = parse_money_or_number(values.get("单位成本（元）"), cents=True)
        if error or unit_cost is None or unit_cost < 0:
            problems.append("单位成本必须为非负数")
        return_text = normalize_text(values.get("退货入库数量"))
        return_qty = 0
        if return_text:
            return_qty, error = parse_money_or_number(return_text, cents=False)
            if error or return_qty is None or return_qty < 0:
                problems.append("退货入库数量必须为非负整数")
        return_unit_cost = 0
        if return_qty:
            return_unit_cost, error = parse_money_or_number(
                values.get("退货单位成本（元）"), cents=True
            )
            if error or return_unit_cost is None or return_unit_cost < 0:
                problems.append("有退货时必须填写退货单位成本")
        if not identifier:
            problems.append("子订单号为空")
        elif identifier not in valid_ids:
            problems.append("子订单号未在当前结算账单中找到")
        if identifier in seen:
            problems.append("子订单号重复")
        seen.add(identifier)
        if outbound_qty is not None and return_qty is not None and return_qty > outbound_qty:
            problems.append("退货入库数量不能大于出库数量")
        outbound = (outbound_qty or 0) * (unit_cost or 0)
        reversal = (return_qty or 0) * (return_unit_cost or 0)
        amount = outbound - reversal
        if not problems:
            outbound_total += outbound
            reversal_total += reversal
        rows.append(_result_row(source, identifier, values.get("SKU"), amount, problems, {
            "outboundCostCents": outbound,
            "reversalCostCents": reversal,
        }))
    return _finish_result(rows, outboundTotalCents=outbound_total,
                          reversalTotalCents=reversal_total,
                          netCostCents=outbound_total - reversal_total)


def _calculate_fulfillment_rows(source_rows, valid_ids):
    rows = []
    seen = set()
    total = 0
    for source in source_rows:
        values = source["values"]
        identifier = normalize_identifier(values.get("子订单号"))
        problems = []
        components = []
        for field in ("快递费（元）", "仓储费（元）", "其他履约费（元）"):
            value, error = parse_money_or_number(values.get(field) or "0", cents=True)
            if error or value is None or value < 0:
                problems.append("{}必须为非负数".format(field))
                value = 0
            components.append(value)
        if not identifier:
            problems.append("子订单号为空")
        elif identifier not in valid_ids:
            problems.append("子订单号未在当前结算账单中找到")
        if identifier in seen:
            problems.append("子订单号重复")
        seen.add(identifier)
        amount = sum(components)
        if amount <= 0:
            problems.append("履约费合计必须大于0")
        if not problems:
            total += amount
        rows.append(_result_row(source, identifier, None, amount, problems, {
            "courierCents": components[0],
            "storageCents": components[1],
            "otherCents": components[2],
        }))
    return _finish_result(rows, fulfillmentExpenseCents=total)


def _calculate_operating_expense_rows(source_rows, task_store_name):
    rows = []
    seen = set()
    total = 0
    excluded = 0
    for source in source_rows:
        values = source["values"]
        identifier = normalize_identifier(values.get("原始单号"))
        problems = []
        amount, error = parse_money_or_number(values.get("金额（元）"), cents=True)
        if error or amount is None or amount < 0:
            problems.append("金额必须为非负数")
            amount = 0
        if not identifier:
            problems.append("原始单号为空")
        if identifier in seen:
            problems.append("原始单号重复")
        seen.add(identifier)
        if normalize_text(values.get("归属店铺")) != task_store_name:
            problems.append("归属店铺与当前任务不一致")
        included = normalize_text(values.get("是否计入本期")) == "是"
        if not included:
            excluded += amount
        elif not problems:
            total += amount
        rows.append(_result_row(source, identifier, values.get("费用类别"),
                                amount if included else 0, problems, {
                                    "included": included,
                                    "sourceAmountCents": amount,
                                }))
    return _finish_result(rows, operatingExpenseCents=total,
                          excludedExpenseCents=excluded)


def _result_row(source, identifier, secondary, amount, problems, extra):
    return {
        "sheetName": None,
        "rowNumber": source["rowNumber"],
        "primaryIdentifier": identifier or None,
        "secondaryIdentifier": normalize_text(secondary) or None,
        "status": "needs_attention" if problems else "matched",
        "amountCents": amount,
        "explanation": "；".join(problems) if problems else "模拟资料已按试算映射通过",
        "rawValues": values_to_json_safe(source["values"]),
        "details": extra,
    }


def _finish_result(rows, **summary):
    matched = [row for row in rows if row["status"] == "matched"]
    attention = len(rows) - len(matched)
    total_amount = sum(row["amountCents"] for row in matched)
    summary.update({
        "totalRowCount": len(rows),
        "matchedRowCount": len(matched),
        "attentionCount": attention,
        "totalAmountCents": total_amount,
    })
    return {
        "status": "passed" if rows and attention == 0 else "needs_attention",
        "totalRowCount": len(rows),
        "matchedRowCount": len(matched),
        "attentionCount": attention,
        "totalAmountCents": total_amount,
        "summary": summary,
        "rows": rows,
    }


def values_to_json_safe(values):
    return {str(key): value for key, value in values.items()}
