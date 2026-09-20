import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from .data_import import (
    normalize_identifier,
    normalize_text,
    parse_excel_datetime,
    parse_money_or_number,
)
from .xlsx import extract_defined_workbook_rows, inspect_defined_workbook


MAPPING_VERSION = "M018-SIM-1"
SIMULATED_AS_OF = "2026-08-08T12:00:00"
DEFAULT_WAIT_DAYS = 7

PENDING_SETTLEMENT_SHEETS = (
    {
        "name": "待结算订单",
        "header_row": 5,
        "data_start_row": 6,
        "required_headers": (
            "测试场景编号", "订单编号", "子订单编号", "商品ID",
            "订单支付金额", "订单状态", "结算状态", "结算周期",
            "预计结算时间", "预计结算金额",
        ),
    },
    {
        "name": "订单售后辅助",
        "header_row": 5,
        "data_start_row": 6,
        "required_headers": (
            "测试场景编号", "订单编号", "子订单编号", "订单完成时间",
            "订单状态", "售后状态", "限制或冻结状态", "是否已进入结算账单",
        ),
    },
)

ATTENTION_STATUSES = {
    "overdue",
    "after_sales",
    "restricted",
    "insufficient",
    "source_anomaly",
    "invalid_source",
}


def inspect_pending_settlement_workbook(file_path):
    inspected = inspect_defined_workbook(file_path, PENDING_SETTLEMENT_SHEETS)
    inspected["mappingVersion"] = MAPPING_VERSION
    inspected["trialMode"] = True
    inspected["mappingNotice"] = (
        "当前按M018模拟字段映射试运行；真实待结算文件到位后再冻结表头和状态枚举。"
    )
    return inspected


def calculate_pending_settlement(
    file_path,
    task_period,
    wait_days=DEFAULT_WAIT_DAYS,
    as_of=SIMULATED_AS_OF,
):
    if wait_days <= 0:
        raise ValueError("等待天数必须大于0")
    as_of_time = datetime.fromisoformat(as_of)
    workbook_rows = extract_defined_workbook_rows(
        file_path, PENDING_SETTLEMENT_SHEETS
    )
    source_rows = []
    pending_rows = []
    auxiliary_rows = []
    invalid_results = []

    for source in workbook_rows.get("待结算订单", []):
        source_rows.append(_source_row("pending_order", "待结算订单", source))
        parsed, errors = _parse_pending_row(source)
        if errors:
            invalid_results.append(_invalid_result("待结算订单", source, errors))
        else:
            pending_rows.append(parsed)

    for source in workbook_rows.get("订单售后辅助", []):
        source_rows.append(_source_row("order_auxiliary", "订单售后辅助", source))
        parsed, errors = _parse_auxiliary_row(source)
        if errors:
            invalid_results.append(_invalid_result("订单售后辅助", source, errors))
        else:
            auxiliary_rows.append(parsed)

    duplicate_pending = _duplicate_scenes(pending_rows)
    duplicate_auxiliary = _duplicate_scenes(auxiliary_rows)
    for duplicated, sheet_name in (
        (duplicate_pending, "待结算订单"),
        (duplicate_auxiliary, "订单售后辅助"),
    ):
        for scene_code, items in duplicated.items():
            invalid_results.append(_duplicate_result(sheet_name, scene_code, items))

    pending_rows = [item for item in pending_rows if item["sceneCode"] not in duplicate_pending]
    auxiliary_rows = [item for item in auxiliary_rows if item["sceneCode"] not in duplicate_auxiliary]
    auxiliary_by_scene = {item["sceneCode"]: item for item in auxiliary_rows}
    pending_scenes = {item["sceneCode"] for item in pending_rows}

    results = []
    for pending in pending_rows:
        auxiliary = auxiliary_by_scene.get(pending["sceneCode"])
        results.append(
            _classify_pending(pending, auxiliary, as_of_time, wait_days)
        )

    for auxiliary in auxiliary_rows:
        if auxiliary["sceneCode"] in pending_scenes:
            continue
        results.append(_classify_excluded(auxiliary))

    results.extend(invalid_results)
    status_counts = dict(Counter(item["status"] for item in results))
    attention_count = sum(item["status"] in ATTENTION_STATUSES for item in results)
    pending_amount_cents = sum(
        item["expectedSettlementCents"] or 0
        for item in results
        if item["sourceType"] == "pending_order"
    )
    return {
        "mappingVersion": MAPPING_VERSION,
        "trialMode": True,
        "enforcementMode": "informational",
        "resultType": "pending_settlement",
        "resultLabel": "待结算订单跟踪",
        "taskPeriod": task_period,
        "asOf": as_of,
        "waitDays": wait_days,
        "status": "needs_attention" if attention_count else "passed",
        "totalResultCount": len(results),
        "attentionCount": attention_count,
        "waitingCount": status_counts.get("waiting", 0),
        "overdueCount": status_counts.get("overdue", 0),
        "excludedCount": status_counts.get("canceled_refunded", 0),
        "pendingSourceCount": len(pending_rows),
        "pendingAmountCents": pending_amount_cents,
        "statusCounts": status_counts,
        "sourceRowCount": len(source_rows),
        "sourceRows": source_rows,
        "results": results,
    }


def _classify_pending(pending, auxiliary, as_of_time, wait_days):
    auxiliary = auxiliary or {
        "sceneCode": pending["sceneCode"],
        "orderId": pending["orderId"],
        "suborderId": pending["suborderId"],
        "completedAt": None,
        "orderStatus": pending["orderStatus"],
        "afterSalesStatus": "",
        "restrictionStatus": "",
        "enteredSettlement": "",
        "rowNumber": None,
    }
    order_status = auxiliary["orderStatus"] or pending["orderStatus"]
    after_sales = auxiliary["afterSalesStatus"]
    restriction = auxiliary["restrictionStatus"]
    entered_settlement = auxiliary["enteredSettlement"]
    settlement_status = pending["settlementStatus"]
    expected_at = pending["expectedSettlementAt"]
    completed_at = auxiliary["completedAt"]
    recheck_at = None

    if order_status in ("已取消", "已退款") or after_sales == "退款成功":
        status = "canceled_refunded"
        explanation = "订单已取消或退款，不再作为普通待结算订单追踪。"
        suggestion = "确认最终关闭；如已退款，改到退款链路核对。"
        completion = "取消/退款资料与平台账户变化一致"
    elif restriction in ("账户冻结", "违规限制") or settlement_status in (
        "冻结处理中（模拟）", "违规限制（模拟）"
    ):
        status = "restricted"
        explanation = "平台限制或冻结优先于普通逾期判断。"
        suggestion = "查看平台通知、违规说明或处理入口。"
        completion = "限制解除并结算，或取得最终退款/关闭结果"
        recheck_at = as_of_time + timedelta(days=1)
    elif after_sales == "售后处理中":
        status = "after_sales"
        explanation = "售后尚未结束，应先等待售后结果，不直接判定平台结算逾期。"
        suggestion = "等待售后结果后重新分类。"
        completion = "售后结束后进入结算、退款或关闭链路"
        recheck_at = as_of_time + timedelta(days=1)
    elif entered_settlement == "是":
        status = "source_anomaly"
        explanation = "辅助资料显示已进入结算账单，但仍出现在待结算清单。"
        suggestion = "核对导出时点、订单粒度和是否部分结算。"
        completion = "确认待结算与已结算记录不再冲突"
    elif expected_at:
        expected_time = datetime.fromisoformat(expected_at)
        if as_of_time < expected_time:
            status = "waiting"
            explanation = "平台预计结算时间晚于本次核对时间。"
            suggestion = "等待平台处理。"
            completion = "进入结算账单或状态改变"
            recheck_at = expected_time
        else:
            status = "overdue"
            explanation = "已到平台预计结算时间，且没有售后、取消、冻结或限制原因。"
            suggestion = "查看平台详情并继续跟踪。"
            completion = "已结算，或取得可追溯的延期原因"
            recheck_at = as_of_time + timedelta(days=1)
    elif not completed_at:
        status = "insufficient"
        explanation = "没有平台预计结算时间，也没有可用的订单完成时间。"
        suggestion = "补充真实待结算文件或订单完成时间。"
        completion = "补充资料后重新运行"
    else:
        deadline = datetime.fromisoformat(completed_at) + timedelta(days=wait_days)
        if as_of_time <= deadline:
            status = "waiting"
            explanation = "无平台预计时间，按订单完成时间加{}个自然日；本次核对尚未超过边界。".format(wait_days)
            suggestion = "等待下次检查。"
            completion = "进入结算账单，或超过当前等待期后重新分类"
            recheck_at = deadline + timedelta(seconds=1)
        else:
            status = "overdue"
            explanation = "无平台预计时间，订单完成时间加{}天后已超过本次核对时间。".format(wait_days)
            suggestion = "查看平台详情并继续跟踪。"
            completion = "已结算，或取得可追溯的延期原因"
            recheck_at = as_of_time + timedelta(days=1)

    return _result(
        pending,
        auxiliary,
        status,
        explanation,
        suggestion,
        completion,
        recheck_at,
        "pending_order",
        "待结算订单",
        pending["rowNumber"],
    )


def _classify_excluded(auxiliary):
    if auxiliary["orderStatus"] in ("已取消", "已退款") or auxiliary["afterSalesStatus"] == "退款成功":
        status = "canceled_refunded"
        explanation = "订单已取消或退款，未出现在待结算清单符合当前预期。"
        suggestion = "不继续追普通结算；退款订单改到退款链路核对。"
        completion = "确认最终关闭，且无未收商家应收"
    elif auxiliary["enteredSettlement"] == "是":
        status = "settled_excluded"
        explanation = "订单已进入结算账单，不应继续留在待结算清单。"
        suggestion = "转入已结算核对。"
        completion = "结算账单与平台资金完成核对"
    else:
        status = "source_anomaly"
        explanation = "辅助资料中有订单，但待结算清单中没有，且暂无取消、退款或已结算原因。"
        suggestion = "检查待结算导出范围、订单粒度和漏行。"
        completion = "补入待结算清单，或记录可追溯的排除原因"
    empty_pending = {
        "sceneCode": auxiliary["sceneCode"],
        "orderId": auxiliary["orderId"],
        "suborderId": auxiliary["suborderId"],
        "productId": None,
        "paymentCents": None,
        "orderStatus": auxiliary["orderStatus"],
        "settlementStatus": None,
        "settlementCycle": None,
        "expectedSettlementAt": None,
        "expectedSettlementCents": None,
        "rowNumber": None,
    }
    return _result(
        empty_pending,
        auxiliary,
        status,
        explanation,
        suggestion,
        completion,
        None,
        "order_auxiliary",
        "订单售后辅助",
        auxiliary["rowNumber"],
    )


def _result(
    pending,
    auxiliary,
    status,
    explanation,
    suggestion,
    completion,
    recheck_at,
    source_type,
    source_sheet,
    source_row_number,
):
    return {
        "status": status,
        "sceneCode": pending["sceneCode"],
        "orderId": pending["orderId"],
        "suborderId": pending["suborderId"],
        "productId": pending["productId"],
        "paymentCents": pending["paymentCents"],
        "orderStatus": auxiliary["orderStatus"] or pending["orderStatus"],
        "settlementStatus": pending["settlementStatus"],
        "settlementCycle": pending["settlementCycle"],
        "expectedSettlementAt": pending["expectedSettlementAt"],
        "expectedSettlementCents": pending["expectedSettlementCents"],
        "completedAt": auxiliary["completedAt"],
        "afterSalesStatus": auxiliary["afterSalesStatus"],
        "restrictionStatus": auxiliary["restrictionStatus"],
        "enteredSettlement": auxiliary["enteredSettlement"],
        "recheckAt": recheck_at.replace(microsecond=0).isoformat() if recheck_at else None,
        "completionCondition": completion,
        "sourceType": source_type,
        "sourceSheet": source_sheet,
        "sourceRowNumber": source_row_number,
        "auxSourceSheet": (
            "订单售后辅助"
            if source_type == "pending_order" and auxiliary.get("rowNumber")
            else None
        ),
        "auxSourceRowNumber": (
            auxiliary.get("rowNumber")
            if source_type == "pending_order"
            else None
        ),
        "metadata": {},
        "explanation": explanation,
        "suggestion": suggestion,
    }


def _parse_pending_row(source):
    values = source["values"]
    errors = []
    scene_code = normalize_text(values.get("测试场景编号"))
    order_id = normalize_identifier(values.get("订单编号"))
    suborder_id = normalize_identifier(values.get("子订单编号"))
    product_id = normalize_identifier(values.get("商品ID"))
    payment_cents, payment_error = parse_money_or_number(values.get("订单支付金额"), cents=True)
    expected_cents, expected_error = parse_money_or_number(values.get("预计结算金额"), cents=True)
    expected_at, expected_date_error = _parse_optional_datetime(values.get("预计结算时间"))
    if not scene_code:
        errors.append("测试场景编号为空")
    if not order_id:
        errors.append("订单编号为空")
    if not suborder_id:
        errors.append("子订单编号为空")
    if not normalize_text(values.get("订单状态")):
        errors.append("订单状态为空")
    if payment_error:
        errors.append("订单支付金额{}".format(payment_error))
    if expected_error:
        errors.append("预计结算金额{}".format(expected_error))
    if expected_date_error:
        errors.append("预计结算时间{}".format(expected_date_error))
    return ({
        "sceneCode": scene_code,
        "orderId": order_id,
        "suborderId": suborder_id,
        "productId": product_id or None,
        "paymentCents": payment_cents,
        "orderStatus": normalize_text(values.get("订单状态")),
        "settlementStatus": normalize_text(values.get("结算状态")) or None,
        "settlementCycle": normalize_text(values.get("结算周期")) or None,
        "expectedSettlementAt": expected_at,
        "expectedSettlementCents": expected_cents,
        "rowNumber": source["rowNumber"],
    }, errors)


def _parse_auxiliary_row(source):
    values = source["values"]
    errors = []
    scene_code = normalize_text(values.get("测试场景编号"))
    order_id = normalize_identifier(values.get("订单编号"))
    suborder_id = normalize_identifier(values.get("子订单编号"))
    completed_at, completed_error = _parse_optional_datetime(values.get("订单完成时间"))
    if not scene_code:
        errors.append("测试场景编号为空")
    if not order_id:
        errors.append("订单编号为空")
    if not suborder_id:
        errors.append("子订单编号为空")
    if not normalize_text(values.get("订单状态")):
        errors.append("订单状态为空")
    if completed_error:
        errors.append("订单完成时间{}".format(completed_error))
    return ({
        "sceneCode": scene_code,
        "orderId": order_id,
        "suborderId": suborder_id,
        "completedAt": completed_at,
        "orderStatus": normalize_text(values.get("订单状态")),
        "afterSalesStatus": normalize_text(values.get("售后状态")),
        "restrictionStatus": normalize_text(values.get("限制或冻结状态")),
        "enteredSettlement": normalize_text(values.get("是否已进入结算账单")),
        "rowNumber": source["rowNumber"],
    }, errors)


def _parse_optional_datetime(value):
    if not normalize_text(value):
        return None, None
    return parse_excel_datetime(value)


def _duplicate_scenes(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["sceneCode"]].append(row)
    return {key: items for key, items in grouped.items() if key and len(items) > 1}


def _duplicate_result(sheet_name, scene_code, items):
    first = items[0]
    return {
        "status": "invalid_source",
        "sceneCode": scene_code,
        "orderId": first.get("orderId"),
        "suborderId": first.get("suborderId"),
        "productId": first.get("productId"),
        "paymentCents": first.get("paymentCents"),
        "orderStatus": first.get("orderStatus"),
        "settlementStatus": first.get("settlementStatus"),
        "settlementCycle": first.get("settlementCycle"),
        "expectedSettlementAt": first.get("expectedSettlementAt"),
        "expectedSettlementCents": first.get("expectedSettlementCents"),
        "completedAt": first.get("completedAt"),
        "afterSalesStatus": first.get("afterSalesStatus"),
        "restrictionStatus": first.get("restrictionStatus"),
        "enteredSettlement": first.get("enteredSettlement"),
        "recheckAt": None,
        "completionCondition": "测试场景编号唯一后重新运行",
        "sourceType": "invalid_source",
        "sourceSheet": sheet_name,
        "sourceRowNumber": first["rowNumber"],
        "auxSourceSheet": None,
        "auxSourceRowNumber": None,
        "metadata": {"duplicateCount": len(items)},
        "explanation": "测试场景编号{}重复，无法唯一连接待结算和辅助资料。".format(scene_code),
        "suggestion": "回到{}检查重复行。".format(sheet_name),
    }


def _source_row(record_type, sheet_name, source):
    return {
        "recordType": record_type,
        "sheetName": sheet_name,
        "rowNumber": source["rowNumber"],
        "rawValuesJson": json.dumps(source["values"], ensure_ascii=False, separators=(",", ":")),
    }


def _invalid_result(sheet_name, source, errors):
    values = source["values"]
    return {
        "status": "invalid_source",
        "sceneCode": normalize_text(values.get("测试场景编号")) or "UNKNOWN",
        "orderId": normalize_identifier(values.get("订单编号")) or None,
        "suborderId": normalize_identifier(values.get("子订单编号")) or None,
        "productId": normalize_identifier(values.get("商品ID")) or None,
        "paymentCents": None,
        "orderStatus": normalize_text(values.get("订单状态")) or None,
        "settlementStatus": normalize_text(values.get("结算状态")) or None,
        "settlementCycle": normalize_text(values.get("结算周期")) or None,
        "expectedSettlementAt": None,
        "expectedSettlementCents": None,
        "completedAt": None,
        "afterSalesStatus": normalize_text(values.get("售后状态")) or None,
        "restrictionStatus": normalize_text(values.get("限制或冻结状态")) or None,
        "enteredSettlement": normalize_text(values.get("是否已进入结算账单")) or None,
        "recheckAt": None,
        "completionCondition": "源数据修正后重新运行",
        "sourceType": "invalid_source",
        "sourceSheet": sheet_name,
        "sourceRowNumber": source["rowNumber"],
        "auxSourceSheet": None,
        "auxSourceRowNumber": None,
        "metadata": {"errors": errors},
        "explanation": "源数据无法分类：{}。".format("；".join(errors)),
        "suggestion": "修正对应Excel行后重新导入。",
    }
