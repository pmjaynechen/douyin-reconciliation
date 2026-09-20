import json

from .data_import import parse_money_or_number


ORDER_CHECK = {
    "code": "R01_ORDER_PAYABLE",
    "label": "订单应付金额",
    "source": "订单应付金额",
}

SETTLEMENT_CHECKS = (
    {
        "code": "R02_ORDER_TOTAL",
        "label": "订单总价",
        "source": "订单总价",
        "fields": ("商品总价", "运费"),
    },
    {
        "code": "R02_INCOME_TOTAL",
        "label": "收入合计",
        "source": "收入合计",
        "fields": ("用户实付", "平台补贴", "达人补贴", "抖音支付补贴", "抖音月付营销补贴"),
    },
    {
        "code": "R02_EXPENSE_TOTAL",
        "label": "支出合计",
        "source": "支出合计",
        "fields": ("平台服务费", "佣金", "渠道分成", "招商服务费", "站外推广费", "其他分成"),
    },
    {
        "code": "R02_SETTLEMENT_AMOUNT",
        "label": "结算金额",
        "source": "结算金额",
        "fields": ("收入合计", "支出合计"),
    },
)


def calculate_amount_checks(records, tolerance_cents):
    results = []
    for record in records:
        values = json.loads(record["rawValuesJson"])
        if record["recordType"] == "order":
            results.append(_calculate_order(record, values, tolerance_cents))
        elif record["recordType"] == "settlement":
            for definition in SETTLEMENT_CHECKS:
                results.append(
                    _calculate_sum(record, values, definition, tolerance_cents)
                )
    return _summarize(results, tolerance_cents)


def _calculate_order(record, values, tolerance_cents):
    required = (
        "商品金额",
        "商品数量",
        "运费",
        "平台实际承担优惠金额",
        "商家实际承担优惠金额",
        "达人实际承担优惠金额",
    )
    parsed, error = _parse_fields(values, required)
    source_cents, source_error = parse_money_or_number(values.get(ORDER_CHECK["source"]), cents=True)
    if error or source_error:
        return _result(
            record,
            ORDER_CHECK,
            "not_calculable",
            source_cents,
            None,
            None,
            error or "平台订单应付金额无法读取",
        )
    quantity, quantity_error = parse_money_or_number(values.get("商品数量"), cents=False)
    if quantity_error:
        return _result(record, ORDER_CHECK, "not_calculable", source_cents, None, None, quantity_error)
    calculated = (
        parsed["商品金额"] * quantity
        + parsed["运费"]
        - parsed["平台实际承担优惠金额"]
        - parsed["商家实际承担优惠金额"]
        - parsed["达人实际承担优惠金额"]
    )
    return _compare(record, ORDER_CHECK, source_cents, calculated, tolerance_cents)


def _calculate_sum(record, values, definition, tolerance_cents):
    parsed, error = _parse_fields(values, definition["fields"])
    source_cents, source_error = parse_money_or_number(values.get(definition["source"]), cents=True)
    if error or source_error:
        return _result(
            record,
            definition,
            "not_calculable",
            source_cents,
            None,
            None,
            error or "平台{}无法读取".format(definition["label"]),
        )
    calculated = sum(parsed.values())
    return _compare(record, definition, source_cents, calculated, tolerance_cents)


def _parse_fields(values, fields):
    parsed = {}
    for field in fields:
        cents, error = parse_money_or_number(values.get(field), cents=True)
        if error:
            return {}, "{}无法读取：{}".format(field, error)
        parsed[field] = cents
    return parsed, None


def _compare(record, definition, source_cents, calculated_cents, tolerance_cents):
    difference = source_cents - calculated_cents
    status = "passed" if abs(difference) <= tolerance_cents else "failed"
    message = None if status == "passed" else "平台金额与系统计算金额差异超过{:.2f}元".format(tolerance_cents / 100)
    return _result(record, definition, status, source_cents, calculated_cents, difference, message)


def _result(record, definition, status, source_cents, calculated_cents, difference_cents, message):
    return {
        "sheetName": record["sheetName"],
        "rowNumber": record["rowNumber"],
        "recordType": record["recordType"],
        "primaryIdentifier": record["primaryIdentifier"],
        "checkCode": definition["code"],
        "checkLabel": definition["label"],
        "status": status,
        "sourceAmountCents": source_cents,
        "calculatedAmountCents": calculated_cents,
        "differenceCents": difference_cents,
        "message": message,
    }


def _summarize(results, tolerance_cents):
    summary = []
    for definition in (ORDER_CHECK,) + SETTLEMENT_CHECKS:
        rows = [item for item in results if item["checkCode"] == definition["code"]]
        summary.append(
            {
                "checkCode": definition["code"],
                "checkLabel": definition["label"],
                "totalCount": len(rows),
                "passedCount": sum(1 for item in rows if item["status"] == "passed"),
                "failedCount": sum(1 for item in rows if item["status"] == "failed"),
                "notCalculableCount": sum(1 for item in rows if item["status"] == "not_calculable"),
                "sourceAmountTotalCents": sum(item["sourceAmountCents"] or 0 for item in rows),
                "differenceTotalCents": sum(item["differenceCents"] or 0 for item in rows),
            }
        )
    return {
        "status": "passed" if all(item["status"] == "passed" for item in results) else "failed",
        "toleranceCents": tolerance_cents,
        "totalCheckCount": len(results),
        "passedCount": sum(1 for item in results if item["status"] == "passed"),
        "failedCount": sum(1 for item in results if item["status"] == "failed"),
        "notCalculableCount": sum(1 for item in results if item["status"] == "not_calculable"),
        "checkSummaries": summary,
        "exceptionPreview": [item for item in results if item["status"] != "passed"][:100],
        "results": results,
    }
