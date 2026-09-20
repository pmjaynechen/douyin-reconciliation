import json
import calendar
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


ORDINARY_SETTLEMENT_TYPE = "已结算"
ORDINARY_FUND_SCENE = "货款结算入账"
REFUND_FUND_SCENE_PREFIX = "退款-"
REFUND_SETTLEMENT_PREFIX = "结算后退款"
CONTROL_RULE_VERSION = 2

AFTER_SALE_STATUS_MAP = {
    "同意退款，退款成功": ("refund_success", "退款成功"),
    "退款成功": ("refund_success", "退款成功"),
    "售后关闭": ("after_sale_closed", "售后关闭"),
    "换货成功": ("exchange_success", "换货成功"),
    "售后处理中": ("waiting_after_sale", "等待售后处理"),
}

FUND_CATEGORY_LABELS = {
    "monthly_interest": "抖音月付联合贴息",
    "shipping_insurance": "运费险类收支",
    "consumer_compensation": "消费者赔付",
    "withdrawal": "提现",
    "waiting_classification": "等待分类",
}


def calculate_supplementary_reconciliation(
    records, historical_order_records=None, settlement_wait_days=7,
    task_period=None, tolerance_cents=1,
):
    """Calculate order-to-settlement controls and R06-R10 classifications."""
    if settlement_wait_days is None or settlement_wait_days <= 0:
        raise ValueError("默认结算等待天数必须大于0")
    if tolerance_cents is None or tolerance_cents < 0:
        raise ValueError("金额容差不能小于0")
    historical_order_records = historical_order_records or []

    cross_month = _calculate_cross_month(
        records,
        historical_order_records,
        settlement_wait_days,
        task_period,
        tolerance_cents,
    )
    after_sales = _calculate_after_sales(records)
    costs = _calculate_costs(records)
    other_funds = _calculate_other_funds(records)
    attention_count = (
        cross_month["attentionCount"]
        + after_sales["attentionCount"]
        + costs["attentionCount"]
        + other_funds["attentionCount"]
    )
    return {
        "status": "needs_attention" if attention_count else "passed",
        "resultType": "supplementary",
        "controlRuleVersion": CONTROL_RULE_VERSION,
        "sourceFieldVersion": 2,
        "settlementWaitDays": settlement_wait_days,
        "attentionCount": attention_count,
        "crossMonth": cross_month,
        "afterSales": after_sales,
        "costs": costs,
        "otherFunds": other_funds,
    }


def classify_expected_settlement(
    as_of, completed_at=None, platform_expected_at=None,
    has_open_after_sale=False, settlement_wait_days=7,
):
    """Classify an unsettled order when the source provides a usable completion date."""
    if settlement_wait_days <= 0:
        raise ValueError("默认结算等待天数必须大于0")
    as_of = _parse_time(as_of)
    completed_at = _parse_time(completed_at)
    platform_expected_at = _parse_time(platform_expected_at)
    if as_of is None:
        return {
            "status": "not_calculable",
            "expectedAt": None,
            "explanation": "缺少核对日期，无法判断是否到预计结算日。",
        }
    expected_at = platform_expected_at
    if expected_at is None and completed_at is not None:
        expected_at = completed_at + timedelta(days=settlement_wait_days)
    if expected_at is None:
        return {
            "status": "not_calculable",
            "expectedAt": None,
            "explanation": "没有平台预计结算日期，也没有确认收货或订单完成时间。",
        }
    if has_open_after_sale:
        return {
            "status": "waiting_after_sale",
            "expectedAt": expected_at.isoformat(),
            "explanation": "售后尚未结束，等待售后处理，不判断平台逾期。",
        }
    if as_of <= expected_at:
        return {
            "status": "normal_waiting",
            "expectedAt": expected_at.isoformat(),
            "explanation": "尚未到预计结算日，属于正常等待。",
        }
    return {
        "status": "possibly_unsettled",
        "expectedAt": expected_at.isoformat(),
        "explanation": "已经超过预计结算日，可能尚未结算，需要继续核实。",
    }


def _calculate_cross_month(
    records, historical_order_records, settlement_wait_days, task_period, tolerance_cents
):
    current_orders = defaultdict(list)
    historical_orders = defaultdict(list)
    settlements = []
    after_sales_by_order = defaultdict(list)
    current_order_times = []
    for record in records:
        values = _raw_values(record)
        if record.get("recordType") == "order":
            if record.get("primaryIdentifier"):
                current_orders[record["primaryIdentifier"]].append(record)
            parsed = _parse_time(record.get("eventTime"))
            if parsed:
                current_order_times.append(parsed)
        elif (
            record.get("recordType") == "settlement"
            and _text(values.get("结算单类型")) == ORDINARY_SETTLEMENT_TYPE
        ):
            settlements.append(record)
        elif record.get("recordType") == "after_sale" and record.get("secondaryIdentifier"):
            after_sales_by_order[record["secondaryIdentifier"]].append(record)
    for record in historical_order_records:
        if record.get("primaryIdentifier"):
            historical_orders[record["primaryIdentifier"]].append(record)

    current_start = min(current_order_times) if current_order_times else None
    as_of = _task_period_end(task_period) or max(current_order_times, default=None)
    results = []
    settled_sub_orders = set()
    for settlement in sorted(settlements, key=lambda item: item.get("rowNumber") or 0):
        sub_order_id = settlement.get("primaryIdentifier")
        if sub_order_id:
            settled_sub_orders.add(sub_order_id)
        current_matches = current_orders.get(sub_order_id, [])
        history_matches = historical_orders.get(sub_order_id, [])
        order_time = _parse_source_time(_raw_values(settlement).get("下单时间"))
        base = {
            "resultType": "cross_month",
            "subOrderId": sub_order_id,
            "sourceRecordId": settlement.get("sourceRecordId"),
            "sourceRowNumber": settlement.get("rowNumber"),
            "linkedSourceRecordId": None,
            "linkedRowNumber": None,
            "amountCents": settlement.get("amountCents"),
            "orderTime": order_time.isoformat() if order_time else None,
            "orderPeriod": order_time.strftime("%Y-%m") if order_time else None,
            "historicalTaskId": None,
            "historicalFileId": None,
            "historicalTaskPeriod": None,
            "recordKind": "settlement_link",
            "expectedMerchantReceivableCents": None,
            "settlementIncomeCents": _money_cents(_raw_values(settlement).get("收入合计")),
            "receivableDifferenceCents": None,
            "explanation": "",
            "suggestion": "",
        }
        if len(current_matches) == 1:
            order = current_matches[0]
            results.append(_check_order_settlement_amount(base, order, "order_found_current", tolerance_cents))
        elif len(history_matches) == 1:
            order = history_matches[0]
            history_base = {
                **base,
                "historicalTaskId": order.get("taskId"),
                "historicalFileId": order.get("fileVersionId"),
                "historicalTaskPeriod": order.get("taskPeriod"),
            }
            results.append(_check_order_settlement_amount(
                history_base, order, "order_found_history", tolerance_cents
            ))
        elif len(history_matches) > 1:
            results.append({
                **base,
                "status": "multiple_history_orders",
                "explanation": "历史任务中找到多条同一子订单，系统不能自动选择。",
                "suggestion": "检查历史文件版本和重复编号后再确认。",
            })
        else:
            is_historical = order_time is not None and current_start is not None and order_time < current_start
            results.append({
                **base,
                "status": "missing_historical_order",
                "explanation": (
                    "该结算对应的订单早于本次订单文件范围，当前没有历史订单资料；这不是平台少结。"
                    if is_historical
                    else "本次及已导入历史订单中都没有找到该子订单，属于缺少订单资料；这不是平台少结。"
                ),
                "suggestion": "补充更早期间订单明细后重新计算。",
            })

    for sub_order_id, orders in sorted(current_orders.items()):
        if sub_order_id in settled_sub_orders:
            continue
        for order in sorted(orders, key=lambda item: item.get("rowNumber") or 0):
            results.append(_classify_unsettled_order(
                order,
                after_sales_by_order.get(sub_order_id, []),
                as_of,
                settlement_wait_days,
                tolerance_cents,
            ))

    counts = Counter(item["status"] for item in results)
    attention_statuses = {
        "missing_historical_order", "missing_order_data", "multiple_history_orders",
        "settlement_receivable_mismatch", "settlement_receivable_not_calculable",
        "settlement_before_refund_review", "possibly_unsettled", "not_calculable",
        "order_status_requires_review",
    }
    attention = sum(counts[key] for key in attention_statuses)
    return {
        "status": "needs_attention" if attention else "passed",
        "totalResultCount": len(results),
        "settlementResultCount": len(settlements),
        "unsettledOrderCount": sum(1 for item in results if item.get("recordKind") == "unsettled_order"),
        "currentOrderFoundCount": counts["order_found_current"],
        "historicalOrderFoundCount": counts["order_found_history"],
        "missingHistoricalOrderCount": counts["missing_historical_order"],
        "missingOrderDataCount": counts["missing_order_data"],
        "multipleHistoryOrderCount": counts["multiple_history_orders"],
        "receivableMatchedCount": counts["order_found_current"] + counts["order_found_history"],
        "receivableMismatchCount": counts["settlement_receivable_mismatch"],
        "possiblyUnsettledCount": counts["possibly_unsettled"],
        "normalWaitingCount": counts["normal_waiting"] + counts["waiting_after_sale"],
        "fullyRefundedNoSettlementCount": counts["fully_refunded_no_settlement"],
        "closedNoSettlementCount": counts["closed_no_settlement"],
        "attentionCount": attention,
        "statusCounts": dict(counts),
        "currentOrderDateFrom": current_start.date().isoformat() if current_start else None,
        "results": results,
    }


def _check_order_settlement_amount(base, order, found_status, tolerance_cents):
    order_values = _raw_values(order)
    expected = _expected_merchant_receivable_cents(order)
    income = base.get("settlementIncomeCents")
    common = {
        **base,
        "linkedSourceRecordId": order.get("sourceRecordId"),
        "linkedRowNumber": order.get("rowNumber"),
        "expectedMerchantReceivableCents": expected,
        "receivableDifferenceCents": income - expected
        if income is not None and expected is not None else None,
    }
    before_refund = _money_cents(order_values.get("结算前退款金额"))
    before_refund_flag = _text(order_values.get("有结算前退款"))
    if (before_refund is not None and before_refund != 0) or before_refund_flag not in ("", "否"):
        return {
            **common,
            "status": "settlement_before_refund_review",
            "explanation": "订单存在结算前退款，当前样本还不足以确认统一应收口径。",
            "suggestion": "核对订单应收、结算前退款和结算收入，确认后再处理。",
        }
    if expected is None or income is None:
        return {
            **common,
            "status": "settlement_receivable_not_calculable",
            "explanation": "已找到订单，但订单应收或结算收入缺失，无法完成金额勾稽。",
            "suggestion": "修正订单支付金额、平台/达人承担优惠或结算收入合计后重新导入。",
        }
    if abs(income - expected) > tolerance_cents:
        return {
            **common,
            "status": "settlement_receivable_mismatch",
            "explanation": "订单应收与结算收入合计差异超过金额容差。",
            "suggestion": "查看订单优惠承担、结算前退款及结算调整项。",
        }
    return {
        **common,
        "status": found_status,
        "explanation": (
            "已在本次订单明细中找到同一子订单，且订单应收与结算收入一致。"
            if found_status == "order_found_current"
            else "已在历史任务中找到同一子订单，且订单应收与结算收入一致。"
        ),
        "suggestion": "无需处理。",
    }


def _classify_unsettled_order(order, after_sales, as_of, settlement_wait_days, tolerance_cents):
    values = _raw_values(order)
    sub_order_id = order.get("primaryIdentifier")
    order_status = _text(values.get("订单状态"))
    successful_refund = sum(
        item.get("amountCents") or 0
        for item in after_sales
        if "退款成功" in _text(_raw_values(item).get("售后状态"))
    )
    base = {
        "resultType": "cross_month",
        "recordKind": "unsettled_order",
        "subOrderId": sub_order_id,
        "sourceRecordId": order.get("sourceRecordId"),
        "sourceRowNumber": order.get("rowNumber"),
        "linkedSourceRecordId": None,
        "linkedRowNumber": None,
        "amountCents": order.get("amountCents"),
        "orderTime": order.get("eventTime"),
        "orderPeriod": _period_of(order.get("eventTime")),
        "orderStatus": order_status,
        "completedAt": _source_time_text(values.get("订单完成时间")),
        "successfulRefundCents": successful_refund,
        "expectedAt": None,
        "explanation": "",
        "suggestion": "",
    }
    if order_status == "已关闭":
        return {**base, "status": "closed_no_settlement", "explanation": "订单已关闭，无需等待普通结算。", "suggestion": "无需处理。"}
    if order.get("amountCents") is not None and successful_refund >= order["amountCents"] - tolerance_cents:
        return {**base, "status": "fully_refunded_no_settlement", "explanation": "订单已成功全额退款，不再期待普通结算。", "suggestion": "无需处理。"}
    if order_status != "已完成":
        return {**base, "status": "order_status_requires_review", "explanation": "订单尚未形成普通结算，且当前状态不是已完成、已关闭或全额退款。", "suggestion": "核对订单状态和结算条件。"}
    open_after_sale = any(
        not any(final in _text(_raw_values(item).get("售后状态")) for final in ("退款成功", "售后关闭", "换货成功"))
        for item in after_sales
    )
    classification = classify_expected_settlement(
        as_of,
        completed_at=values.get("订单完成时间"),
        has_open_after_sale=open_after_sale,
        settlement_wait_days=settlement_wait_days,
    )
    return {
        **base,
        **classification,
        "suggestion": (
            "查看平台结算账期、售后和结算单，确认是否少结或资料未覆盖。"
            if classification["status"] in ("possibly_unsettled", "not_calculable")
            else "暂无需处理，到预计结算日后再复核。"
        ),
    }


def _calculate_after_sales(records):
    after_sales = [item for item in records if item.get("recordType") == "after_sale"]
    refund_settlements = [
        item for item in records
        if item.get("recordType") == "settlement"
        and _text(_raw_values(item).get("结算单类型")).startswith(REFUND_SETTLEMENT_PREFIX)
    ]
    refund_fund_keys = defaultdict(list)
    for item in records:
        if item.get("recordType") != "fund":
            continue
        values = _raw_values(item)
        if not _text(values.get("动账场景")).startswith(REFUND_FUND_SCENE_PREFIX):
            continue
        after_sale_id = _identifier(values.get("售后编号"))
        if item.get("secondaryIdentifier") and after_sale_id:
            refund_fund_keys[(item["secondaryIdentifier"], after_sale_id)].append(item)
    refund_settlement_suborders = {
        item.get("primaryIdentifier") for item in refund_settlements if item.get("primaryIdentifier")
    }
    after_sale_keys = set()
    by_sub_order = Counter(
        item.get("secondaryIdentifier") for item in after_sales if item.get("secondaryIdentifier")
    )
    multi_ids = {key for key, count in by_sub_order.items() if count > 1}
    results = []
    for record in sorted(after_sales, key=lambda item: item.get("rowNumber") or 0):
        values = _raw_values(record)
        source_status = _text(values.get("售后状态"))
        status_info = AFTER_SALE_STATUS_MAP.get(source_status)
        if status_info:
            status, label = status_info
            if status == "waiting_after_sale":
                explanation = "售后仍在处理中，等待平台给出最终结果。"
                suggestion = "售后结束后重新导入最新数据。"
            else:
                explanation = {
                    "refund_success": "退款已经成功，可作为已发生退款展示。",
                    "after_sale_closed": "售后已关闭，不能当作退款成功。",
                    "exchange_success": "换货已经完成，但不能直接当作现金退款。",
                }[status]
                suggestion = "无需处理。"
        elif source_status:
            status, label = "new_after_sale_status", "新售后状态"
            explanation = "当前规则未配置这个售后状态，系统已停止自动判断。"
            suggestion = "核实平台状态含义后再分类。"
        else:
            status, label = "waiting_after_sale", "等待售后处理"
            explanation = "售后状态为空或尚未结束，等待售后处理。"
            suggestion = "补充或更新售后状态后重新计算。"
        sub_order_id = record.get("secondaryIdentifier")
        after_sale_id = record.get("primaryIdentifier") or _identifier(values.get("售后单号"))
        if sub_order_id and after_sale_id:
            after_sale_keys.add((sub_order_id, after_sale_id))
        has_refund_evidence = (
            sub_order_id in refund_settlement_suborders
            and bool(refund_fund_keys.get((sub_order_id, after_sale_id)))
        )
        if has_refund_evidence and status in ("after_sale_closed", "exchange_success"):
            status = "after_sale_refund_conflict"
            label = "售后与退款冲突"
            explanation = "售后状态为{}，但已找到同一子订单和售后编号的退款结算与资金记录。".format(source_status)
            suggestion = "核对售后最终状态、退款结算和资金原始行，不能自动当作退款成功。"
        results.append({
            "resultType": "after_sale",
            "status": status,
            "statusLabel": label,
            "afterSaleId": after_sale_id,
            "subOrderId": sub_order_id,
            "sourceRecordId": record.get("sourceRecordId"),
            "sourceRowNumber": record.get("rowNumber"),
            "amountCents": record.get("amountCents"),
            "afterSaleType": _text(values.get("售后类型")),
            "sourceStatus": source_status,
            "sameOrderAfterSaleCount": by_sub_order.get(sub_order_id, 0),
            "isMultipleAfterSaleOrder": sub_order_id in multi_ids,
            "explanation": explanation,
            "suggestion": suggestion,
        })

    for settlement in sorted(refund_settlements, key=lambda item: item.get("rowNumber") or 0):
        sub_order_id = settlement.get("primaryIdentifier")
        candidate_keys = sorted(
            key for key in refund_fund_keys if key[0] == sub_order_id
        )
        for key in candidate_keys:
            if key in after_sale_keys:
                continue
            results.append({
                "resultType": "after_sale",
                "recordKind": "refund_missing_after_sale",
                "status": "refund_missing_after_sale",
                "statusLabel": "退款缺少售后单",
                "afterSaleId": key[1],
                "subOrderId": sub_order_id,
                "sourceRecordId": settlement.get("sourceRecordId"),
                "sourceRowNumber": settlement.get("rowNumber"),
                "amountCents": settlement.get("amountCents"),
                "afterSaleType": None,
                "sourceStatus": None,
                "sameOrderAfterSaleCount": by_sub_order.get(sub_order_id, 0),
                "isMultipleAfterSaleOrder": sub_order_id in multi_ids,
                "explanation": "已找到退款结算和同售后编号的退款资金，但售后表没有该售后单。",
                "suggestion": "补充覆盖该售后编号的售后文件后重新导入。",
            })
    counts = Counter(item["status"] for item in results)
    attention = (
        counts["new_after_sale_status"]
        + counts["after_sale_refund_conflict"]
        + counts["refund_missing_after_sale"]
    )
    return {
        "status": "needs_attention" if attention else "passed",
        "totalResultCount": len(results),
        "refundSuccessCount": counts["refund_success"],
        "closedCount": counts["after_sale_closed"],
        "exchangeSuccessCount": counts["exchange_success"],
        "waitingCount": counts["waiting_after_sale"],
        "unknownCount": counts["new_after_sale_status"],
        "refundConflictCount": counts["after_sale_refund_conflict"],
        "refundMissingAfterSaleCount": counts["refund_missing_after_sale"],
        "multipleAfterSaleOrderCount": len(multi_ids),
        "attentionCount": attention,
        "statusCounts": dict(counts),
        "results": results,
    }


def _calculate_costs(records):
    orders = [item for item in records if item.get("recordType") == "order"]
    costs_by_model = defaultdict(list)
    for record in records:
        if record.get("recordType") == "cost" and record.get("primaryIdentifier"):
            costs_by_model[record["primaryIdentifier"]].append(record)
    results = []
    for order in sorted(orders, key=lambda item: item.get("rowNumber") or 0):
        values = _raw_values(order)
        sku = _identifier(values.get("货号"))
        quantity = _parse_quantity(values.get("商品数量"))
        candidates = costs_by_model.get(sku, []) if sku else []
        base = {
            "resultType": "cost",
            "subOrderId": order.get("primaryIdentifier"),
            "sku": sku or None,
            "sourceRecordId": order.get("sourceRecordId"),
            "sourceRowNumber": order.get("rowNumber"),
            "linkedSourceRecordId": None,
            "linkedRowNumber": None,
            "orderAmountCents": order.get("amountCents"),
            "unitCostCents": None,
            "quantity": quantity,
            "totalCostCents": None,
            "explanation": "",
            "suggestion": "",
        }
        if not sku:
            results.append({
                **base,
                "status": "missing_sku",
                "explanation": "订单缺少货号，无法关联商品成本。",
                "suggestion": "补充货号后重新导入；当前不计算成本。",
            })
        elif len(candidates) > 1:
            results.append({
                **base,
                "status": "multiple_cost_candidates",
                "explanation": "同一型号找到多条静态成本，系统不能自动选择。",
                "suggestion": "检查成本表重复型号和生效期间。",
            })
        elif not candidates:
            results.append({
                **base,
                "status": "missing_cost",
                "explanation": "成本表没有该商品型号，无法计算成本。",
                "suggestion": "在成本表补充该型号后重新导入。",
            })
        elif quantity is None:
            results.append({
                **base,
                "status": "not_calculable",
                "explanation": "商品数量无法计算，成本关联未执行。",
                "suggestion": "修正商品数量后重新导入。",
            })
        else:
            cost = candidates[0]
            unit_cost = cost.get("amountCents")
            if unit_cost is None:
                results.append({
                    **base,
                    "status": "not_calculable",
                    "linkedSourceRecordId": cost.get("sourceRecordId"),
                    "linkedRowNumber": cost.get("rowNumber"),
                    "explanation": "找到商品型号，但成本价无法计算。",
                    "suggestion": "修正成本价后重新导入。",
                })
            else:
                results.append({
                    **base,
                    "status": "matched_static_cost",
                    "linkedSourceRecordId": cost.get("sourceRecordId"),
                    "linkedRowNumber": cost.get("rowNumber"),
                    "unitCostCents": unit_cost,
                    "totalCostCents": int(unit_cost * quantity),
                    "explanation": "已按订单货号关联当前静态成本。",
                    "suggestion": "可用于本次练习测算；正式历史利润需补充成本生效日期。",
                })
    counts = Counter(item["status"] for item in results)
    attention = len(results) - counts["matched_static_cost"]
    return {
        "status": "needs_attention" if attention else "passed",
        "totalResultCount": len(results),
        "matchedCount": counts["matched_static_cost"],
        "missingSkuCount": counts["missing_sku"],
        "missingCostCount": counts["missing_cost"],
        "multipleCandidateCount": counts["multiple_cost_candidates"],
        "notCalculableCount": counts["not_calculable"],
        "attentionCount": attention,
        "matchedStaticCostTotalCents": sum(
            item.get("totalCostCents") or 0
            for item in results if item["status"] == "matched_static_cost"
        ),
        "staticCostWarning": True,
        "statusCounts": dict(counts),
        "results": results,
    }


def _calculate_other_funds(records):
    results = []
    for record in sorted(records, key=lambda item: item.get("rowNumber") or 0):
        if record.get("recordType") != "fund":
            continue
        values = _raw_values(record)
        scene = _text(values.get("动账场景"))
        if scene == ORDINARY_FUND_SCENE or scene.startswith(REFUND_FUND_SCENE_PREFIX):
            continue
        remark = _text(values.get("备注"))
        category = _classify_other_fund(scene, remark)
        status = "waiting_classification" if category == "waiting_classification" else "classified"
        if category == "withdrawal":
            explanation = "这是抖店平台账户转出，不代表企业银行已经到账。"
            suggestion = "单独展示；如需核对银行到账，应另行导入企业银行流水。"
        elif category == "waiting_classification":
            explanation = "当前规则无法识别该平台收支，未并入普通结算差异。"
            suggestion = "查看平台原名称、计费类型和备注后人工分类。"
        else:
            explanation = "已按平台场景和备注归入{}，不并入普通结算差异。".format(
                FUND_CATEGORY_LABELS[category]
            )
            suggestion = "单独查看该类平台账户收支。"
        results.append({
            "resultType": "other_fund",
            "status": status,
            "category": category,
            "categoryLabel": FUND_CATEGORY_LABELS[category],
            "transactionId": record.get("primaryIdentifier"),
            "subOrderId": record.get("secondaryIdentifier"),
            "sourceRecordId": record.get("sourceRecordId"),
            "sourceRowNumber": record.get("rowNumber"),
            "amountCents": record.get("amountCents"),
            "eventTime": record.get("eventTime"),
            "scene": scene,
            "chargeType": _text(values.get("计费类型")),
            "remark": remark,
            "explanation": explanation,
            "suggestion": suggestion,
        })
    category_counts = Counter(item["category"] for item in results)
    category_totals = Counter()
    for item in results:
        category_totals[item["category"]] += item.get("amountCents") or 0
    attention = category_counts["waiting_classification"]
    return {
        "status": "needs_attention" if attention else "passed",
        "totalResultCount": len(results),
        "classifiedCount": len(results) - attention,
        "attentionCount": attention,
        "netAmountTotalCents": sum(item.get("amountCents") or 0 for item in results),
        "categoryCounts": dict(category_counts),
        "categoryTotalsCents": dict(category_totals),
        "results": results,
    }


def _classify_other_fund(scene, remark):
    if scene == "抖音月付与商家联合贴息活动":
        return "monthly_interest"
    if scene == "消费者赔付":
        return "consumer_compensation"
    if scene == "提现":
        return "withdrawal"
    if not scene and (
        "运费险" in remark
        or "HOME-DELIVERY-YXD" in remark
        or "服务类判罚退款" in remark
    ):
        return "shipping_insurance"
    return "waiting_classification"


def _raw_values(record):
    raw = record.get("rawValuesJson") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _text(value):
    return " ".join(str(value).strip().split()) if value is not None else ""


def _identifier(value):
    return _text(value).lstrip("'")


def _parse_quantity(value):
    if value is None or value == "":
        return None
    try:
        quantity = Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    if quantity < 0:
        return None
    return int(quantity) if quantity == quantity.to_integral_value() else float(quantity)


def _money_cents(value, blank_zero=False):
    if value is None or value == "":
        return 0 if blank_zero else None
    try:
        amount = Decimal(str(value).replace(",", "").replace("¥", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _expected_merchant_receivable_cents(order):
    if order.get("amountCents") is None:
        return None
    values = _raw_values(order)
    platform_discount = _money_cents(
        values.get("平台实际承担优惠金额"), blank_zero=True
    )
    creator_discount = _money_cents(
        values.get("达人实际承担优惠金额"), blank_zero=True
    )
    if platform_discount is None or creator_discount is None:
        return None
    return order["amountCents"] + platform_discount + creator_discount


def _task_period_end(task_period):
    if not task_period:
        return None
    try:
        year, month = (int(part) for part in str(task_period).split("-", 1))
        last_day = calendar.monthrange(year, month)[1]
        return datetime(year, month, last_day, 23, 59, 59)
    except (TypeError, ValueError):
        return None


def _source_time_text(value):
    parsed = _parse_source_time(value)
    return parsed.isoformat() if parsed else None


def _period_of(value):
    parsed = _parse_source_time(value)
    return parsed.strftime("%Y-%m") if parsed else None


def _parse_source_time(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime(1899, 12, 30) + timedelta(days=float(value))
    return _parse_time(value)


def _parse_time(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, pattern)
            except ValueError:
                continue
    return None
