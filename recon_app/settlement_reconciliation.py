import json
from collections import defaultdict
from datetime import datetime


ORDINARY_SETTLEMENT_TYPE = "已结算"
ORDINARY_FUND_SCENE = "货款结算入账"
ORDINARY_FUND_DIRECTION = "入账"
ORDINARY_TIME_WARNING_SECONDS = 24 * 60 * 60
CONTROL_RULE_VERSION = 2


def calculate_ordinary_settlement_reconciliation(records, tolerance_cents):
    """Match ordinary settlement rows to platform-account inflows by sub-order."""
    if tolerance_cents is None or tolerance_cents < 0:
        raise ValueError("金额容差不能小于0")

    settlements = []
    funds_by_sub_order = defaultdict(list)
    for record in records:
        values = _raw_values(record)
        if record.get("recordType") == "settlement":
            if _text(values.get("结算单类型")) == ORDINARY_SETTLEMENT_TYPE:
                settlements.append(record)
        elif record.get("recordType") == "fund":
            if (
                _text(values.get("动账场景")) == ORDINARY_FUND_SCENE
                and _text(values.get("动账方向")) == ORDINARY_FUND_DIRECTION
                and record.get("secondaryIdentifier")
            ):
                funds_by_sub_order[record["secondaryIdentifier"]].append(record)

    results = []
    for settlement in sorted(settlements, key=lambda item: item.get("rowNumber") or 0):
        results.append(
            _match_settlement(
                settlement,
                funds_by_sub_order.get(settlement.get("primaryIdentifier"), []),
                tolerance_cents,
            )
        )

    matched = [item for item in results if item["status"] == "matched"]
    attention = [item for item in results if item["status"] != "matched"]
    settlement_total = sum((item["settlementAmountCents"] or 0) for item in results)
    matched_fund_total = sum((item["fundAmountCents"] or 0) for item in matched)
    return {
        "controlRuleVersion": CONTROL_RULE_VERSION,
        "status": "passed" if not attention else "needs_attention",
        "resultType": "ordinary_settlement",
        "resultLabel": "普通结算",
        "settlementType": ORDINARY_SETTLEMENT_TYPE,
        "fundScene": ORDINARY_FUND_SCENE,
        "fundDirection": ORDINARY_FUND_DIRECTION,
        "toleranceCents": tolerance_cents,
        "totalResultCount": len(results),
        "matchedCount": len(matched),
        "attentionCount": len(attention),
        "settlementAmountTotalCents": settlement_total,
        "matchedFundAmountTotalCents": matched_fund_total,
        "differenceTotalCents": matched_fund_total - sum(
            (item["settlementAmountCents"] or 0) for item in matched
        ),
        "statusCounts": _status_counts(results),
        "results": results,
    }


def _match_settlement(settlement, candidates, tolerance_cents):
    settlement_amount = settlement.get("amountCents")
    settlement_values = _raw_values(settlement)
    settlement_account = _text(settlement_values.get("结算账户"))
    base = {
        "status": None,
        "subOrderId": settlement.get("primaryIdentifier"),
        "settlementRowNumber": settlement.get("rowNumber"),
        "settlementAmountCents": settlement_amount,
        "fundRowNumber": None,
        "fundTransactionId": None,
        "fundAmountCents": None,
        "differenceCents": None,
        "candidateCount": len(candidates),
        "matchedCandidateCount": 0,
        "settlementAccount": settlement_account or None,
        "timeWarningSeconds": ORDINARY_TIME_WARNING_SECONDS,
        "timeDifferenceSeconds": None,
        "timeAnomaly": False,
        "candidateRecords": [_candidate_to_api(item) for item in candidates],
        "explanation": "",
        "suggestion": "",
    }
    if settlement_amount is None:
        return {
            **base,
            "status": "not_calculable",
            "explanation": "结算金额无法计算，普通结算核对未执行。",
            "suggestion": "修正结算账单金额后重新导入。",
        }

    account_candidates = [
        item for item in candidates
        if _text(_raw_values(item).get("动账账户")) == settlement_account
    ]
    if candidates and not account_candidates:
        return {
            **base,
            "status": "not_calculable",
            "explanation": "找到了同一子订单的货款入账，但结算账户与资金账户不一致，已停止自动通过。",
            "suggestion": "核对结算账户和资金账户；确认跨账户流转前不要人工判断为核对一致。",
        }

    comparable = [item for item in account_candidates if item.get("amountCents") is not None]
    amount_matches = [
        item
        for item in comparable
        if abs(item["amountCents"] - settlement_amount) <= tolerance_cents
    ]
    base["matchedCandidateCount"] = len(amount_matches)

    if len(amount_matches) == 1:
        fund = amount_matches[0]
        time_difference = _time_difference_seconds(
            settlement.get("eventTime"), fund.get("eventTime")
        )
        time_anomaly = (
            time_difference is not None
            and time_difference > ORDINARY_TIME_WARNING_SECONDS
        )
        return {
            **base,
            "status": "matched",
            "fundRowNumber": fund.get("rowNumber"),
            "fundTransactionId": fund.get("primaryIdentifier"),
            "fundAmountCents": fund.get("amountCents"),
            "differenceCents": fund.get("amountCents") - settlement_amount,
            "timeDifferenceSeconds": time_difference,
            "timeAnomaly": time_anomaly,
            "explanation": (
                "子订单号、账户、动账场景和金额均一致，且最终只有一笔资金记录；"
                "但结算与动账时间相差超过24小时，当前作为时间预警。"
                if time_anomaly
                else "子订单号、账户、动账场景和金额均一致，且最终只有一笔资金记录。"
            ),
            "suggestion": "核实跨日结算是否符合平台批次规律。" if time_anomaly else "无需处理。",
        }

    if len(amount_matches) > 1:
        return {
            **base,
            "status": "multiple_candidates",
            "explanation": "同一子订单有多笔金额符合容差的货款结算入账，系统不能唯一判断。",
            "suggestion": "查看候选资金流水，确认应关联哪一笔后再处理。",
        }

    if not candidates:
        return {
            **base,
            "status": "missing_fund",
            "explanation": "未找到同一子订单的货款结算入账。",
            "suggestion": "确认资金账单是否覆盖对应结算日期，必要时补充账单后重新导入。",
        }

    if not comparable:
        return {
            **base,
            "status": "not_calculable",
            "explanation": "找到了对应子订单的资金记录，但资金金额无法计算。",
            "suggestion": "修正资金账单金额后重新导入。",
        }

    closest = min(
        comparable,
        key=lambda item: (abs(item["amountCents"] - settlement_amount), item.get("rowNumber") or 0),
    )
    return {
        **base,
        "status": "amount_mismatch",
        "fundRowNumber": closest.get("rowNumber"),
        "fundTransactionId": closest.get("primaryIdentifier"),
        "fundAmountCents": closest.get("amountCents"),
        "differenceCents": closest.get("amountCents") - settlement_amount,
        "explanation": "找到了同一子订单的货款结算入账，但金额差超过允许容差。",
        "suggestion": "对照结算账单与资金账单原始行，确认是否存在拆分、合并或源数据错误。",
    }


def _candidate_to_api(record):
    values = _raw_values(record)
    return {
        "rowNumber": record.get("rowNumber"),
        "transactionId": record.get("primaryIdentifier"),
        "amountCents": record.get("amountCents"),
        "account": _text(values.get("动账账户")) or None,
        "eventTime": record.get("eventTime"),
    }


def _time_difference_seconds(left, right):
    left_time = _parse_time(left)
    right_time = _parse_time(right)
    if left_time is None or right_time is None:
        return None
    return int(abs((right_time - left_time).total_seconds()))


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


def _status_counts(results):
    counts = {
        "matched": 0,
        "missing_fund": 0,
        "amount_mismatch": 0,
        "multiple_candidates": 0,
        "not_calculable": 0,
    }
    for item in results:
        counts[item["status"]] += 1
    return counts
