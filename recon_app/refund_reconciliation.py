import json
from collections import defaultdict
from datetime import datetime

from .refund_component_checks import attach_refund_component_checks


REFUND_SETTLEMENT_PREFIX = "结算后退款"
REFUND_FUND_SCENE_PREFIX = "退款-"
CONTROL_RULE_VERSION = 2


def calculate_refund_settlement_reconciliation(
    records, tolerance_cents, auto_group_seconds, candidate_seconds
):
    """Reconcile refund settlements with the net of one after-sale fund group."""
    if tolerance_cents is None or tolerance_cents < 0:
        raise ValueError("金额容差不能小于0")
    if auto_group_seconds is None or auto_group_seconds <= 0:
        raise ValueError("自动归组时间不能小于等于0")
    if candidate_seconds is None or candidate_seconds <= auto_group_seconds:
        raise ValueError("候选时间必须大于自动归组时间")

    settlements = []
    all_settlements = []
    funds = []
    after_sales = []
    funds_by_sub_order = defaultdict(list)
    for record in records:
        values = _raw_values(record)
        if record.get("recordType") == "settlement":
            all_settlements.append(record)
            if _text(values.get("结算单类型")).startswith(REFUND_SETTLEMENT_PREFIX):
                settlements.append(record)
        elif record.get("recordType") == "fund":
            funds.append(record)
            scene = _text(values.get("动账场景"))
            if scene.startswith(REFUND_FUND_SCENE_PREFIX) and record.get("secondaryIdentifier"):
                funds_by_sub_order[record["secondaryIdentifier"]].append(record)
        elif record.get("recordType") == "after_sale":
            after_sales.append(record)

    results = []
    for settlement in sorted(settlements, key=lambda item: item.get("rowNumber") or 0):
        results.append(
            _match_refund_settlement(
                settlement,
                funds_by_sub_order.get(settlement.get("primaryIdentifier"), []),
                tolerance_cents,
                auto_group_seconds,
                candidate_seconds,
            )
        )
    _stop_reused_fund_groups(results)
    _enforce_successful_after_sales(results, after_sales)
    component_summary = attach_refund_component_checks(
        results, all_settlements, funds, after_sales, tolerance_cents
    )

    matched = [item for item in results if item["status"] == "matched"]
    attention = [item for item in results if item["status"] != "matched"]
    settlement_total = sum((item["settlementAmountCents"] or 0) for item in results)
    matched_fund_total = sum((item["fundNetAmountCents"] or 0) for item in matched)
    return {
        "status": "passed" if not attention else "needs_attention",
        "resultType": "refund_settlement",
        "resultLabel": "退款结算",
        "controlRuleVersion": CONTROL_RULE_VERSION,
        "settlementTypePrefix": REFUND_SETTLEMENT_PREFIX,
        "fundScenePrefix": REFUND_FUND_SCENE_PREFIX,
        "toleranceCents": tolerance_cents,
        "autoGroupSeconds": auto_group_seconds,
        "candidateSeconds": candidate_seconds,
        "totalResultCount": len(results),
        "matchedCount": len(matched),
        "attentionCount": len(attention),
        "settlementAmountTotalCents": settlement_total,
        "matchedFundAmountTotalCents": matched_fund_total,
        "differenceTotalCents": matched_fund_total
        - sum((item["settlementAmountCents"] or 0) for item in matched),
        "statusCounts": _status_counts(results),
        **component_summary,
        "results": results,
    }


def _match_refund_settlement(
    settlement, candidates, tolerance_cents, auto_group_seconds, candidate_seconds
):
    settlement_amount = settlement.get("amountCents")
    settlement_time = _parse_time(settlement.get("eventTime"))
    base = {
        "status": None,
        "subOrderId": settlement.get("primaryIdentifier"),
        "settlementRowNumber": settlement.get("rowNumber"),
        "settlementAmountCents": settlement_amount,
        "fundNetAmountCents": None,
        "differenceCents": None,
        "candidateCount": 0,
        "candidateGroupCount": 0,
        "matchedCandidateCount": 0,
        "selectedRecords": [],
        "candidateGroups": [],
        "afterSaleId": None,
        "maxTimeDifferenceSeconds": None,
        "explanation": "",
        "suggestion": "",
    }
    if settlement_amount is None or settlement_time is None:
        return {
            **base,
            "status": "not_calculable",
            "explanation": "结算金额或结算时间无法计算，退款净额归组未执行。",
            "suggestion": "修正结算账单金额和时间后重新导入。",
        }

    in_window = []
    outside_count = 0
    for candidate in candidates:
        candidate_time = _parse_time(candidate.get("eventTime"))
        if candidate_time is None:
            in_window.append(candidate)
            continue
        distance = abs((candidate_time - settlement_time).total_seconds())
        if distance <= candidate_seconds:
            in_window.append(candidate)
        else:
            outside_count += 1

    groups = _build_after_sale_groups(
        in_window, settlement_time, settlement_amount, tolerance_cents, auto_group_seconds
    )
    base["candidateCount"] = len(in_window)
    base["candidateGroupCount"] = len(groups)
    base["candidateGroups"] = groups
    comparable_groups = [group for group in groups if group["comparable"]]
    amount_matches = [group for group in comparable_groups if group["amountMatches"]]
    base["matchedCandidateCount"] = len(amount_matches)

    auto_matches = [group for group in amount_matches if group["autoWindow"]]
    if len(auto_matches) == 1 and len(amount_matches) == 1:
        selected = auto_matches[0]
        return {
            **base,
            "status": "matched",
            "fundNetAmountCents": selected["netAmountCents"],
            "differenceCents": selected["differenceCents"],
            "selectedRecords": selected["records"],
            "afterSaleId": selected["afterSaleId"],
            "maxTimeDifferenceSeconds": selected["maxTimeDifferenceSeconds"],
            "explanation": "同一子订单、同一售后编号的退款资金净额与结算金额一致，且时间差在自动归组窗口内。",
            "suggestion": "无需处理。",
        }

    if len(amount_matches) > 1:
        return {
            **base,
            "status": "multiple_candidates",
            "explanation": "同一子订单有多个售后资金组的净额都符合容差，系统不能唯一判断。",
            "suggestion": "核对售后编号和原始资金行，保留候选组后人工确认。",
        }

    if len(amount_matches) == 1:
        selected = amount_matches[0]
        if selected["maxTimeDifferenceSeconds"] is None:
            return {
                **base,
                "status": "not_calculable",
                "fundNetAmountCents": selected["netAmountCents"],
                "differenceCents": selected["differenceCents"],
                "afterSaleId": selected["afterSaleId"],
                "explanation": "退款资金净额一致，但资金时间缺失，无法确认是否在自动归组窗口内。",
                "suggestion": "修正资金账单时间后重新导入。",
            }
        return {
            **base,
            "status": "outside_auto_window",
            "fundNetAmountCents": selected["netAmountCents"],
            "differenceCents": selected["differenceCents"],
            "afterSaleId": selected["afterSaleId"],
            "maxTimeDifferenceSeconds": selected["maxTimeDifferenceSeconds"],
            "explanation": "退款资金净额一致，但时间差超过自动归组窗口，只能作为候选。",
            "suggestion": "核对售后编号和原始资金行后人工确认。",
        }

    if not in_window:
        extra = "；同子订单有{}笔退款资金已超过候选窗口".format(outside_count) if outside_count else ""
        return {
            **base,
            "status": "missing_fund",
            "explanation": "候选时间内未找到同一子订单的退款资金记录{}。".format(extra),
            "suggestion": "确认资金账单是否覆盖退款日期，必要时补充账单后重新导入。",
        }

    if not comparable_groups:
        return {
            **base,
            "status": "not_calculable",
            "explanation": "找到了退款资金记录，但售后编号或金额不完整，无法归成可比较的净额组。",
            "suggestion": "修正资金账单售后编号和金额后重新导入。",
        }

    closest = min(
        comparable_groups,
        key=lambda group: (abs(group["differenceCents"]), group["afterSaleId"]),
    )
    return {
        **base,
        "status": "amount_mismatch",
        "fundNetAmountCents": closest["netAmountCents"],
        "differenceCents": closest["differenceCents"],
        "afterSaleId": closest["afterSaleId"],
        "maxTimeDifferenceSeconds": closest["maxTimeDifferenceSeconds"],
        "explanation": "找到了同一子订单的退款资金组，但净额与结算金额的差超过容差。",
        "suggestion": "对照结算账单与资金账单原始行，确认是否缺少退用户、费用返还或补贴扣回流水。",
    }


def _build_after_sale_groups(
    candidates, settlement_time, settlement_amount, tolerance_cents, auto_group_seconds
):
    grouped = defaultdict(list)
    missing_index = 0
    for candidate in candidates:
        values = _raw_values(candidate)
        after_sale_id = _identifier(values.get("售后编号"))
        if after_sale_id:
            key = after_sale_id
        else:
            missing_index += 1
            key = "__missing__{}".format(missing_index)
        grouped[key].append(candidate)

    groups = []
    for key, items in grouped.items():
        after_sale_id = None if key.startswith("__missing__") else key
        records = [_candidate_to_api(item, settlement_time) for item in items]
        comparable = after_sale_id is not None and all(item.get("amountCents") is not None for item in items)
        net_amount = sum(item["amountCents"] for item in items) if comparable else None
        times = [_parse_time(item.get("eventTime")) for item in items]
        max_distance = None
        if all(time is not None for time in times):
            max_distance = int(max(abs((time - settlement_time).total_seconds()) for time in times))
        difference = net_amount - settlement_amount if net_amount is not None else None
        groups.append(
            {
                "afterSaleId": after_sale_id,
                "recordCount": len(records),
                "records": records,
                "netAmountCents": net_amount,
                "differenceCents": difference,
                "maxTimeDifferenceSeconds": max_distance,
                "autoWindow": max_distance is not None and max_distance <= auto_group_seconds,
                "comparable": comparable,
                "amountMatches": difference is not None and abs(difference) <= tolerance_cents,
            }
        )
    return sorted(
        groups,
        key=lambda group: (
            group["afterSaleId"] is None,
            abs(group["differenceCents"]) if group["differenceCents"] is not None else 10**30,
            group["afterSaleId"] or "",
        ),
    )


def _candidate_to_api(record, settlement_time):
    values = _raw_values(record)
    event_time = _parse_time(record.get("eventTime"))
    return {
        "sourceRecordId": record.get("sourceRecordId"),
        "rowNumber": record.get("rowNumber"),
        "transactionId": record.get("primaryIdentifier"),
        "eventTime": record.get("eventTime"),
        "amountCents": record.get("amountCents"),
        "direction": _text(values.get("动账方向")),
        "scene": _text(values.get("动账场景")),
        "afterSaleId": _identifier(values.get("售后编号")) or None,
        "timeDifferenceSeconds": int(abs((event_time - settlement_time).total_seconds()))
        if event_time is not None
        else None,
    }


def _stop_reused_fund_groups(results):
    usage = defaultdict(list)
    for index, result in enumerate(results):
        if result["status"] == "matched":
            for record in result["selectedRecords"]:
                identity = record.get("sourceRecordId") or (record.get("rowNumber"), record.get("transactionId"))
                usage[identity].append(index)
    conflicts = {index for indexes in usage.values() if len(indexes) > 1 for index in indexes}
    for index in conflicts:
        result = results[index]
        result["status"] = "multiple_candidates"
        result["fundNetAmountCents"] = None
        result["differenceCents"] = None
        result["selectedRecords"] = []
        result["explanation"] = "同一组退款资金同时被多笔结算记录命中，系统已停止自动归组。"
        result["suggestion"] = "核对结算原始行与售后编号，确认每组资金只归属一笔结算。"


def _enforce_successful_after_sales(results, after_sales):
    """Only a uniquely identified successful refund may pass R05."""
    by_key = defaultdict(list)
    for record in after_sales:
        values = _raw_values(record)
        after_sale_id = _identifier(values.get("售后单号")) or record.get("primaryIdentifier")
        sub_order_id = record.get("secondaryIdentifier") or _identifier(values.get("商品单号"))
        if after_sale_id and sub_order_id:
            by_key[(sub_order_id, after_sale_id)].append(record)

    for result in results:
        if result.get("status") != "matched":
            continue
        matches = by_key.get((result.get("subOrderId"), result.get("afterSaleId")), [])
        if len(matches) != 1:
            result["status"] = "not_calculable"
            result["explanation"] = (
                "退款资金净额虽与结算金额一致，但没有唯一找到同一子订单、同一售后编号的售后记录。"
                if not matches
                else "退款资金净额虽与结算金额一致，但同一子订单和售后编号有多条售后记录。"
            )
            result["suggestion"] = "核对售后文件覆盖范围和重复售后单，修正后重新导入。"
            continue
        source_status = _text(_raw_values(matches[0]).get("售后状态"))
        if "退款成功" not in source_status:
            result["status"] = "not_calculable"
            result["explanation"] = "退款资金净额虽与结算金额一致，但对应售后状态为“{}”，不能作为已成功退款通过。".format(
                source_status or "空"
            )
            result["suggestion"] = "核对售后单最终状态；只有退款成功才能自动核对通过。"


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


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


def _status_counts(results):
    counts = {
        "matched": 0,
        "missing_fund": 0,
        "amount_mismatch": 0,
        "multiple_candidates": 0,
        "outside_auto_window": 0,
        "not_calculable": 0,
    }
    for item in results:
        counts[item["status"]] += 1
    return counts
