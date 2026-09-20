import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


REFUND_SETTLEMENT_PREFIX = "结算后退款"
PLATFORM_SUBSIDY_FIELD = "平台补贴"
OTHER_SUBSIDY_FIELDS = (
    "达人补贴",
    "抖音支付补贴",
    "抖音月付营销补贴",
)
SUCCESSFUL_REFUND_STATUSES = ("退款成功",)


def attach_refund_component_checks(results, settlements, funds, after_sales, tolerance_cents):
    """Attach a non-blocking, course-derived refund component trial calculation."""
    if tolerance_cents is None or tolerance_cents < 0:
        raise ValueError("金额容差不能小于0")

    ordinary_by_sub_order = defaultdict(list)
    settlement_by_row = {}
    after_sales_by_key = defaultdict(list)
    funds_by_identity = {}

    for settlement in settlements:
        settlement_by_row[settlement.get("rowNumber")] = settlement
        values = _raw_values(settlement)
        if not _text(values.get("结算单类型")).startswith(REFUND_SETTLEMENT_PREFIX):
            ordinary_by_sub_order[settlement.get("primaryIdentifier")].append(settlement)
    for after_sale in after_sales:
        values = _raw_values(after_sale)
        after_sale_id = _identifier(values.get("售后单号")) or after_sale.get("primaryIdentifier")
        sub_order_id = after_sale.get("secondaryIdentifier") or _identifier(values.get("商品单号"))
        if after_sale_id and sub_order_id:
            after_sales_by_key[(sub_order_id, after_sale_id)].append(after_sale)
    for fund in funds:
        identity = fund.get("sourceRecordId") or (
            fund.get("rowNumber"),
            fund.get("primaryIdentifier"),
        )
        funds_by_identity[identity] = fund

    for result in results:
        settlement = settlement_by_row.get(result.get("settlementRowNumber"))
        selected_funds = []
        for item in result.get("selectedRecords") or []:
            identity = item.get("sourceRecordId") or (
                item.get("rowNumber"),
                item.get("transactionId"),
            )
            if identity in funds_by_identity:
                selected_funds.append(funds_by_identity[identity])
        check = calculate_refund_component_check(
            settlement,
            selected_funds,
            ordinary_by_sub_order.get(result.get("subOrderId"), []),
            after_sales_by_key.get((result.get("subOrderId"), result.get("afterSaleId")), []),
            tolerance_cents,
        )
        result["componentStatus"] = check["status"]
        result["componentCheck"] = check

    counts = {"matched": 0, "mismatch": 0, "limited": 0, "missing_evidence": 0}
    for result in results:
        counts[result["componentStatus"]] += 1
    return {
        "componentCheckStage": "trial",
        "componentRuleSource": "外部课程资料；部分退款比例公式仍待真实抖店样本确认",
        "componentStatusCounts": counts,
        "componentMatchedCount": counts["matched"],
        "componentMismatchCount": counts["mismatch"],
        "componentLimitedCount": counts["limited"],
        "componentMissingEvidenceCount": counts["missing_evidence"],
    }


def calculate_refund_component_check(
    refund_settlement, selected_funds, ordinary_settlements, after_sales, tolerance_cents
):
    base = {
        "status": "missing_evidence",
        "statusLabel": "资料不足",
        "isTrial": True,
        "ruleSource": "外部课程资料；不是抖店官方规则，部分退款公式待真实样本确认",
        "refundType": None,
        "originalSettlementRowNumber": None,
        "afterSaleRowNumber": None,
        "originalUserPaidCents": None,
        "originalPlatformSubsidyCents": None,
        "refundAmountCents": None,
        "expectedPlatformSubsidyRecaptureCents": None,
        "settlementUserRefundCents": None,
        "settlementPlatformSubsidyRecaptureCents": None,
        "fundUserRefundCents": None,
        "fundPlatformSubsidyRecaptureCents": None,
        "fundUserRefundDifferenceCents": None,
        "settlementUserRefundDifferenceCents": None,
        "settlementPlatformDifferenceCents": None,
        "fundPlatformDifferenceCents": None,
        "uncheckedSubsidyFields": [],
        "explanation": "",
        "suggestion": "",
    }
    if refund_settlement is None:
        return _missing(base, "缺少退款结算记录，无法试算退款构成。", "补充退款结算记录后重新导入。")
    if not selected_funds:
        return _missing(base, "退款净额尚未唯一归组，暂不继续判断退款构成。", "先完成退款资金归组，再查看构成试算。")

    original = _select_original_settlement(refund_settlement, ordinary_settlements)
    if original is None:
        return _missing(
            base,
            "没有唯一找到退款前的原结算记录，无法取得原用户实付和平台补贴。",
            "补充原结算月份或核对同一子订单的多笔结算后重新运行。",
        )
    successful_after_sales = [item for item in after_sales if _is_successful_refund(item)]
    if len(successful_after_sales) != 1:
        return _missing(
            {**base, "originalSettlementRowNumber": original.get("rowNumber")},
            "没有唯一找到与资金售后编号一致且退款成功的售后记录。",
            "核对售后编号、售后状态和售后文件覆盖范围。",
        )

    after_sale = successful_after_sales[0]
    original_values = _raw_values(original)
    refund_values = _raw_values(refund_settlement)
    original_user_paid = _money_cents(original_values.get("用户实付"))
    original_platform_subsidy = _money_cents(original_values.get(PLATFORM_SUBSIDY_FIELD))
    refund_amount = _after_sale_refund_cents(after_sale)
    settlement_user_refund = _absolute_money_cents(refund_values.get("用户实付"))
    settlement_platform_recapture = _absolute_money_cents(
        refund_values.get(PLATFORM_SUBSIDY_FIELD)
    )
    if None in (original_user_paid, original_platform_subsidy, refund_amount):
        return _missing(
            {
                **base,
                "originalSettlementRowNumber": original.get("rowNumber"),
                "afterSaleRowNumber": after_sale.get("rowNumber"),
            },
            "原用户实付、原平台补贴或退款金额不是可计算金额。",
            "修正原结算和售后金额后重新导入。",
        )
    original_user_paid = abs(original_user_paid)
    original_platform_subsidy = abs(original_platform_subsidy)
    refund_amount = abs(refund_amount)
    if original_user_paid <= 0:
        return _missing(
            {
                **base,
                "originalSettlementRowNumber": original.get("rowNumber"),
                "afterSaleRowNumber": after_sale.get("rowNumber"),
                "originalUserPaidCents": original_user_paid,
                "originalPlatformSubsidyCents": original_platform_subsidy,
                "refundAmountCents": refund_amount,
            },
            "原用户实付为0，课程比例公式不能计算。",
            "核对是否属于全补贴订单，并补充该场景的真实平台规则。",
        )

    is_full_refund = refund_amount >= original_user_paid - tolerance_cents
    refund_type = "full" if is_full_refund else "partial"
    if original_platform_subsidy == 0:
        expected_platform_recapture = 0
    elif is_full_refund:
        expected_platform_recapture = original_platform_subsidy
    else:
        expected_platform_recapture = _round_ratio(
            refund_amount, original_user_paid, original_platform_subsidy
        )

    fund_user_refund, fund_platform_recapture, platform_amount_known = _fund_components(
        selected_funds
    )
    unchecked = [
        field
        for field in OTHER_SUBSIDY_FIELDS
        if abs(_money_cents(original_values.get(field)) or 0) > tolerance_cents
    ]
    expected_settlement_user = None if unchecked else refund_amount
    checks = {
        "fundUserRefundMatches": abs(fund_user_refund - refund_amount) <= tolerance_cents,
        "settlementUserRefundMatches": None
        if expected_settlement_user is None or settlement_user_refund is None
        else abs(settlement_user_refund - expected_settlement_user) <= tolerance_cents,
        "settlementPlatformMatches": settlement_platform_recapture is not None
        and abs(settlement_platform_recapture - expected_platform_recapture) <= tolerance_cents,
        "fundPlatformMatches": platform_amount_known
        and abs(fund_platform_recapture - expected_platform_recapture) <= tolerance_cents,
    }
    mismatch = any(value is False for value in checks.values())
    missing_comparison = any(
        checks[key] is None
        for key in ("settlementPlatformMatches", "fundPlatformMatches")
    )
    if mismatch:
        status = "mismatch"
        label = "构成异常（试算）"
        explanation = "退款净额可能一致，但退用户和平台补贴追回的组成与课程公式试算不一致。"
        suggestion = "对照售后退款、退款结算和资金明细，确认是否少退用户、少/多追回平台补贴或资金字段归类错误。"
    elif missing_comparison:
        status = "missing_evidence"
        label = "资料不足"
        explanation = "已经找到原结算和售后，但结算或资金字段不足，不能完成构成试算。"
        suggestion = "补充包含用户退款和实际平台补贴字段的结算、资金明细。"
    elif unchecked:
        status = "limited"
        label = "部分构成已核（试算）"
        explanation = "用户退款和平台补贴已试算一致；订单还包含其他补贴，本规则没有套用同一比例公式。"
        suggestion = "当前无需处理平台补贴；达人、抖音支付或月付补贴等待各自真实规则与样本。"
    else:
        status = "matched"
        label = "构成一致（试算）"
        explanation = "退用户金额和平台补贴追回金额与课程公式试算一致。"
        suggestion = "保留为试运行结果；取得真实部分退款样本后再决定是否转为正式规则。"

    return {
        **base,
        "status": status,
        "statusLabel": label,
        "refundType": refund_type,
        "originalSettlementRowNumber": original.get("rowNumber"),
        "afterSaleRowNumber": after_sale.get("rowNumber"),
        "originalUserPaidCents": original_user_paid,
        "originalPlatformSubsidyCents": original_platform_subsidy,
        "refundAmountCents": refund_amount,
        "expectedPlatformSubsidyRecaptureCents": expected_platform_recapture,
        "settlementUserRefundCents": settlement_user_refund,
        "settlementPlatformSubsidyRecaptureCents": settlement_platform_recapture,
        "fundUserRefundCents": fund_user_refund,
        "fundPlatformSubsidyRecaptureCents": fund_platform_recapture,
        "fundUserRefundDifferenceCents": fund_user_refund - refund_amount,
        "settlementUserRefundDifferenceCents": None
        if expected_settlement_user is None or settlement_user_refund is None
        else settlement_user_refund - expected_settlement_user,
        "settlementPlatformDifferenceCents": None
        if settlement_platform_recapture is None
        else settlement_platform_recapture - expected_platform_recapture,
        "fundPlatformDifferenceCents": None
        if not platform_amount_known
        else fund_platform_recapture - expected_platform_recapture,
        "uncheckedSubsidyFields": unchecked,
        "checks": checks,
        "explanation": explanation,
        "suggestion": suggestion,
    }


def _select_original_settlement(refund_settlement, ordinary_settlements):
    refund_time = _parse_time(refund_settlement.get("eventTime"))
    candidates = []
    for settlement in ordinary_settlements:
        event_time = _parse_time(settlement.get("eventTime"))
        if refund_time is not None and event_time is not None and event_time > refund_time:
            continue
        candidates.append((event_time, settlement))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0] is not None, item[0] or datetime.min), reverse=True)
    latest_time = candidates[0][0]
    latest = [item[1] for item in candidates if item[0] == latest_time]
    return latest[0] if len(latest) == 1 else None


def _after_sale_refund_cents(after_sale):
    values = _raw_values(after_sale)
    goods = _money_cents(values.get("退商品金额（元）"))
    shipping = _money_cents(values.get("退运费金额（元）"))
    if goods is None and shipping is None:
        return after_sale.get("amountCents")
    return (goods or 0) + (shipping or 0)


def _fund_components(funds):
    user_refund = 0
    platform_recapture = 0
    platform_amount_known = True
    for fund in funds:
        values = _raw_values(fund)
        scene = _text(values.get("动账场景"))
        order_refund = _money_cents(values.get("订单退款"))
        if order_refund is not None and order_refund != 0:
            user_refund += abs(order_refund)
        elif "退用户" in scene and fund.get("amountCents") is not None:
            user_refund += abs(fund["amountCents"])
        platform_value = _money_cents(values.get("实际平台补贴"))
        if platform_value is not None:
            platform_recapture += abs(platform_value)
        elif "退补贴" in scene:
            platform_amount_known = False
    return user_refund, platform_recapture, platform_amount_known


def _is_successful_refund(after_sale):
    status = _text(_raw_values(after_sale).get("售后状态"))
    return any(value in status for value in SUCCESSFUL_REFUND_STATUSES)


def _round_ratio(refund_cents, user_paid_cents, subsidy_cents):
    value = (
        Decimal(refund_cents) / Decimal(user_paid_cents) * Decimal(subsidy_cents)
    )
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _money_cents(value):
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _absolute_money_cents(value):
    cents = _money_cents(value)
    return abs(cents) if cents is not None else None


def _raw_values(record):
    if not record:
        return {}
    raw = record.get("rawValuesJson") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _text(value):
    return " ".join(str(value).strip().split()) if value is not None else ""


def _identifier(value):
    return _text(value).lstrip("'")


def _missing(base, explanation, suggestion):
    return {
        **base,
        "status": "missing_evidence",
        "statusLabel": "资料不足",
        "explanation": explanation,
        "suggestion": suggestion,
    }
