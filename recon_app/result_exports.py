import re
from datetime import datetime, timezone

from .export_xlsx import build_xlsx


RESULT_TYPE_LABELS = {
    "wide_reconciliation": "对账明细宽表",
    "ordinary_settlement": "普通结算",
    "refund_settlement": "退款结算",
    "cross_month": "订单与结算",
    "after_sale": "售后状态",
    "cost": "订单成本",
    "other_fund": "其他平台收支",
}

FILTER_LABELS = {
    "all": "全部",
    "matched": "核对一致",
    "cleared": "已处理",
    "needs_attention": "待处理",
}

WIDE_FILTER_LABELS = {
    "all": "全部",
    "needs_attention": "待处理",
    "matched": "核对一致",
    "resolved": "人工已处理（含带到下月）",
    "no_settlement": "未进入结算",
}

WIDE_SCENE_LABELS = {
    "all": "全部场景",
    "ordinary_settlement": "普通结算",
    "refund_settlement": "退款结算",
    "cross_month": "订单与结算",
    "after_sale": "售后",
    "cost": "成本",
    "other_fund": "其他收支",
    "order_only": "仅订单资料",
}


def build_result_export(task, file_version, result_type, status, rows):
    definition = EXPORT_DEFINITIONS[result_type]
    export_time = datetime.now(timezone.utc).replace(microsecond=0)
    metadata = [
        ("导出范围", "当前结果页筛选下的全部明细，不受页面分页限制"),
        ("企业主体", task["entityName"]),
        ("店铺", task["storeName"]),
        ("对账月份", task["period"]),
        ("任务编号", task["id"]),
        ("任务状态", task["status"]),
        ("规则版本", task["ruleVersionLabel"]),
        ("来源文件", file_version["originalName"]),
        ("文件版本编号", file_version["id"]),
        ("结果类型", RESULT_TYPE_LABELS[result_type]),
        ("筛选条件", filter_label(status)),
        ("导出行数", str(len(rows))),
        ("导出时间（UTC）", export_time.isoformat().replace("+00:00", "Z")),
        ("金额单位", "人民币元；金额列为Excel数值，可直接求和"),
        ("编号说明", "订单号、售后单号和流水号均为文本单元格，不会转成科学计数法"),
    ]
    columns = [
        {"label": item[0], "kind": item[1], "width": item[2]}
        for item in definition
    ]
    values = [
        [column[3](row) for column in definition]
        for row in rows
    ]
    return {
        "content": build_xlsx(metadata, columns, values),
        "fileName": export_file_name(task, result_type, status, export_time),
        "rowCount": len(rows),
        "resultTypeLabel": RESULT_TYPE_LABELS[result_type],
        "filterLabel": filter_label(status),
    }


def build_wide_reconciliation_export(
    task, file_version, status, scene, query, rows
):
    export_time = datetime.now(timezone.utc).replace(microsecond=0)
    normalized_query = " ".join(str(query or "").strip().split())
    metadata = [
        ("导出范围", "当前宽表状态、业务场景和编号搜索下的全部明细，不受页面分页限制"),
        ("数据粒度", "一行一个子订单；无法关联子订单的资料单独保留"),
        ("企业主体", task["entityName"]),
        ("店铺", task["storeName"]),
        ("对账月份", task["period"]),
        ("任务编号", task["id"]),
        ("任务状态", task["status"]),
        ("规则版本", task["ruleVersionLabel"]),
        ("来源文件", file_version["originalName"]),
        ("文件版本编号", file_version["id"]),
        ("状态筛选", wide_filter_label(status)),
        ("业务场景", wide_scene_label(scene)),
        ("编号搜索", normalized_query or "未设置"),
        ("导出行数", str(len(rows))),
        ("导出时间（UTC）", export_time.isoformat().replace("+00:00", "Z")),
        ("金额单位", "人民币元；金额列为Excel数值，可直接求和"),
        ("编号说明", "订单号、售后单号和流水号均为文本单元格，不会转成科学计数法"),
        ("证据说明", "来源Excel行保留工作表名、原行号、原编号、时间和金额，便于回查"),
    ]
    columns = [
        {"label": item[0], "kind": item[1], "width": item[2]}
        for item in WIDE_EXPORT_DEFINITION
    ]
    values = [
        [column[3](row) for column in WIDE_EXPORT_DEFINITION]
        for row in rows
    ]
    return {
        "content": build_xlsx(metadata, columns, values),
        "fileName": wide_export_file_name(
            task, status, scene, export_time
        ),
        "rowCount": len(rows),
        "resultTypeLabel": RESULT_TYPE_LABELS["wide_reconciliation"],
        "filterLabel": wide_filter_label(status),
        "sceneLabel": wide_scene_label(scene),
    }


def filter_label(status):
    return FILTER_LABELS.get(status, status)


def wide_filter_label(status):
    return WIDE_FILTER_LABELS.get(status, status)


def wide_scene_label(scene):
    return WIDE_SCENE_LABELS.get(scene, scene)


def export_file_name(task, result_type, status, export_time):
    raw = "{}_{}_{}_{}_{}.xlsx".format(
        task["period"],
        task["storeName"],
        RESULT_TYPE_LABELS[result_type],
        filter_label(status),
        export_time.strftime("%Y%m%d%H%M%S"),
    )
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1F]', "_", raw)
    return cleaned[:180]


def wide_export_file_name(task, status, scene, export_time):
    raw = "{}_{}_{}_{}_{}_{}.xlsx".format(
        task["period"],
        task["storeName"],
        RESULT_TYPE_LABELS["wide_reconciliation"],
        wide_filter_label(status),
        wide_scene_label(scene),
        export_time.strftime("%Y%m%d%H%M%S"),
    )
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1F]', "_", raw)
    return cleaned[:180]


def _manual(row, key):
    resolution = row.get("manualResolution") or {}
    return resolution.get(key)


def _manual_state(row):
    return _manual(row, "resolutionStateLabel") or "系统自动"


def _bool_label(value):
    if value is None:
        return None
    return "是" if value else "否"


def _join_values(values):
    return "、".join(str(value) for value in (values or []) if value not in (None, ""))


def _wide_rule_results(row):
    labels = []
    for result in row.get("results") or []:
        label = "{}：{}".format(
            result.get("resultTypeLabel") or result.get("resultType") or "未知规则",
            result.get("statusLabel") or result.get("status") or "未知状态",
        )
        manual = result.get("manualResolution") or {}
        if manual.get("resolutionStateLabel"):
            label += "（{}）".format(manual["resolutionStateLabel"])
        labels.append(label)
    return "；".join(labels) or "仅有底表资料"


def _source_rows(row):
    values = []
    for source in row.get("sourceRows") or []:
        details = [
            "{}!第{}行".format(source.get("sheetName") or "未知表", source.get("rowNumber") or "?"),
        ]
        if source.get("primaryIdentifier") not in (None, ""):
            details.append("编号={}".format(source["primaryIdentifier"]))
        if source.get("eventTime") not in (None, ""):
            details.append("时间={}".format(source["eventTime"]))
        if source.get("amountCents") is not None:
            details.append("金额={:.2f}".format(source["amountCents"] / 100.0))
        values.append(" | ".join(details))
    return "\n".join(values)


MANUAL_COLUMNS = (
    ("结论来源", "text", 14, _manual_state),
    ("人工处理方式", "text", 18, lambda r: _manual(r, "actionLabel")),
    ("人工选择记录", "text", 24, lambda r: _manual(r, "selectedCandidateKey")),
    ("人工调整金额", "money_cents", 16, lambda r: _manual(r, "adjustedAmountCents")),
    ("跟进日期", "text", 14, lambda r: _manual(r, "followUpDate")),
    ("人工处理原因", "text", 36, lambda r: _manual(r, "reason")),
    ("人工处理时间（UTC）", "datetime", 21, lambda r: _manual(r, "createdAt")),
)


WIDE_EXPORT_DEFINITION = (
    ("核对-状态", "text", 18, lambda r: r.get("statusLabel")),
    ("核对-业务场景", "text", 28, lambda r: _join_values(r.get("sceneLabels"))),
    ("核对-子订单号", "text", 24, lambda r: r.get("subOrderId")),
    ("核对-差额", "money_cents", 16, lambda r: r.get("differenceCents")),
    ("核对-差异原因", "text", 42, lambda r: r.get("reason")),
    ("核对-下一步", "text", 42, lambda r: r.get("suggestion")),
    ("核对-各规则结论", "text", 48, _wide_rule_results),
    ("核对-结果数", "number", 12, lambda r: r.get("resultCount")),
    ("核对-未处理异常数", "number", 16, lambda r: r.get("unresolvedCount")),
    ("核对-人工已处理数", "number", 16, lambda r: r.get("manualResolvedCount")),
    ("订单-主订单号", "text", 24, lambda r: r.get("mainOrderId")),
    ("订单-货号", "text", 20, lambda r: r.get("sku")),
    ("订单-数量", "number", 12, lambda r: r.get("quantity")),
    ("订单-状态", "text", 18, lambda r: r.get("orderStatus")),
    ("订单-类型", "text", 18, lambda r: r.get("orderType")),
    ("订单-提交时间", "datetime", 20, lambda r: r.get("submittedAt")),
    ("订单-商品单价", "money_cents", 16, lambda r: r.get("unitPriceCents")),
    ("订单-运费", "money_cents", 14, lambda r: r.get("shippingCents")),
    ("订单-订单应付", "money_cents", 16, lambda r: r.get("orderPayableCents")),
    ("订单-平台优惠", "money_cents", 16, lambda r: r.get("platformDiscountCents")),
    ("订单-商家优惠", "money_cents", 16, lambda r: r.get("merchantDiscountCents")),
    ("订单-达人优惠", "money_cents", 16, lambda r: r.get("creatorDiscountCents")),
    ("订单-预计商家应收", "money_cents", 20, lambda r: r.get("expectedMerchantReceivableCents")),
    ("订单-应收与结算差额", "money_cents", 20, lambda r: r.get("receivableDifferenceCents")),
    ("售后-售后数", "number", 12, lambda r: r.get("afterSaleCount")),
    ("售后-售后单号", "text", 32, lambda r: _join_values(r.get("afterSaleIds"))),
    ("售后-售后类型", "text", 24, lambda r: _join_values(r.get("afterSaleTypes"))),
    ("售后-售后状态", "text", 30, lambda r: _join_values(r.get("afterSaleStatuses"))),
    ("售后-申请退款金额", "money_cents", 18, lambda r: r.get("afterSaleRequestedRefundCents")),
    ("售后-成功退款金额", "money_cents", 18, lambda r: r.get("afterSaleRefundCents")),
    ("售后-最新售后时间", "datetime", 20, lambda r: r.get("afterSaleLatestAt")),
    ("结算-结算数", "number", 12, lambda r: r.get("settlementCount")),
    ("结算-结算类型", "text", 24, lambda r: _join_values(r.get("settlementTypes"))),
    ("结算-最新结算时间", "datetime", 20, lambda r: r.get("settlementLatestAt")),
    ("结算-收入合计", "money_cents", 16, lambda r: r.get("settlementIncomeCents")),
    ("结算-支出合计", "money_cents", 16, lambda r: r.get("settlementExpenseCents")),
    ("结算-结算净额", "money_cents", 16, lambda r: r.get("settlementNetCents")),
    ("资金-资金数", "number", 12, lambda r: r.get("fundCount")),
    ("资金-动账场景", "text", 30, lambda r: _join_values(r.get("fundScenes"))),
    ("资金-最新动账时间", "datetime", 20, lambda r: r.get("fundLatestAt")),
    ("资金-资金净额", "money_cents", 16, lambda r: r.get("fundNetCents")),
    ("资金-资金流水号", "text", 36, lambda r: _join_values(r.get("fundTransactionIds"))),
    ("成本-成本状态", "text", 18, lambda r: r.get("costStatus")),
    ("成本-单位成本", "money_cents", 16, lambda r: r.get("unitCostCents")),
    ("成本-订单成本", "money_cents", 16, lambda r: r.get("totalCostCents")),
    ("追溯-来源Excel行", "text", 72, _source_rows),
)


EXPORT_DEFINITIONS = {
    "ordinary_settlement": (
        ("系统状态", "text", 16, lambda r: r.get("statusLabel")),
        *MANUAL_COLUMNS,
        ("子订单号", "text", 24, lambda r: r.get("subOrderId")),
        ("结算金额", "money_cents", 16, lambda r: r.get("settlementAmountCents")),
        ("资金金额", "money_cents", 16, lambda r: r.get("fundAmountCents")),
        ("差额", "money_cents", 16, lambda r: r.get("differenceCents")),
        ("结算Excel行", "number", 14, lambda r: r.get("settlementRowNumber")),
        ("资金Excel行", "number", 14, lambda r: r.get("fundRowNumber")),
        ("资金流水号", "text", 28, lambda r: r.get("fundTransactionId")),
        ("候选记录数", "number", 14, lambda r: r.get("candidateCount")),
        ("符合记录数", "number", 14, lambda r: r.get("matchedCandidateCount")),
        ("系统说明", "text", 42, lambda r: r.get("explanation")),
        ("建议动作", "text", 42, lambda r: r.get("suggestion")),
    ),
    "refund_settlement": (
        ("系统状态", "text", 16, lambda r: r.get("statusLabel")),
        *MANUAL_COLUMNS,
        ("子订单号", "text", 24, lambda r: r.get("subOrderId")),
        ("售后编号", "text", 24, lambda r: r.get("afterSaleId")),
        ("退款结算净额", "money_cents", 18, lambda r: r.get("settlementAmountCents")),
        ("资金净额", "money_cents", 16, lambda r: r.get("fundNetAmountCents")),
        ("差额", "money_cents", 16, lambda r: r.get("differenceCents")),
        ("结算Excel行", "number", 14, lambda r: r.get("settlementRowNumber")),
        ("资金行数", "number", 12, lambda r: r.get("selectedRecordCount")),
        ("最大时差（秒）", "number", 16, lambda r: r.get("maxTimeDifferenceSeconds")),
        ("候选组数", "number", 12, lambda r: r.get("candidateGroupCount")),
        ("退款构成试算", "text", 22, lambda r: r.get("componentStatusLabel")),
        ("售后退款金额", "money_cents", 18, lambda r: (r.get("componentCheck") or {}).get("refundAmountCents")),
        ("预计平台补贴追回", "money_cents", 20, lambda r: (r.get("componentCheck") or {}).get("expectedPlatformSubsidyRecaptureCents")),
        ("资金实际退用户", "money_cents", 18, lambda r: (r.get("componentCheck") or {}).get("fundUserRefundCents")),
        ("资金实际追回平台补贴", "money_cents", 22, lambda r: (r.get("componentCheck") or {}).get("fundPlatformSubsidyRecaptureCents")),
        ("构成试算说明", "text", 48, lambda r: (r.get("componentCheck") or {}).get("explanation")),
        ("系统说明", "text", 42, lambda r: r.get("explanation")),
        ("建议动作", "text", 42, lambda r: r.get("suggestion")),
    ),
    "cross_month": (
        ("系统状态", "text", 18, lambda r: r.get("statusLabel")),
        *MANUAL_COLUMNS,
        ("子订单号", "text", 24, lambda r: r.get("subOrderId") or r.get("primaryIdentifier")),
        ("记录类型", "text", 18, lambda r: r.get("recordKind")),
        ("订单状态", "text", 16, lambda r: r.get("orderStatus")),
        ("订单时间", "datetime", 20, lambda r: r.get("orderTime")),
        ("订单完成时间", "datetime", 20, lambda r: r.get("completedAt")),
        ("预计结算时间", "datetime", 20, lambda r: r.get("expectedAt")),
        ("订单月份", "text", 14, lambda r: r.get("orderPeriod")),
        ("历史任务月份", "text", 16, lambda r: r.get("historicalTaskPeriod")),
        ("结算金额", "money_cents", 16, lambda r: r.get("amountCents")),
        ("订单预计商家应收", "money_cents", 20, lambda r: r.get("expectedMerchantReceivableCents")),
        ("结算收入合计", "money_cents", 18, lambda r: r.get("settlementIncomeCents")),
        ("应收与结算差额", "money_cents", 18, lambda r: r.get("receivableDifferenceCents")),
        ("成功退款金额", "money_cents", 18, lambda r: r.get("successfulRefundCents")),
        ("结算Excel行", "number", 14, lambda r: r.get("sourceRowNumber")),
        ("订单Excel行", "number", 14, lambda r: r.get("linkedRowNumber")),
        ("系统说明", "text", 48, lambda r: r.get("explanation")),
        ("建议动作", "text", 42, lambda r: r.get("suggestion")),
    ),
    "after_sale": (
        ("系统状态", "text", 16, lambda r: r.get("statusLabel")),
        *MANUAL_COLUMNS,
        ("售后单号", "text", 24, lambda r: r.get("afterSaleId") or r.get("primaryIdentifier")),
        ("子订单号", "text", 24, lambda r: r.get("subOrderId")),
        ("售后类型", "text", 18, lambda r: r.get("afterSaleType")),
        ("平台状态", "text", 24, lambda r: r.get("sourceStatus")),
        ("退商品金额", "money_cents", 16, lambda r: r.get("amountCents")),
        ("同订单售后数", "number", 16, lambda r: r.get("sameOrderAfterSaleCount")),
        ("是否多次售后", "text", 16, lambda r: _bool_label(r.get("isMultipleAfterSaleOrder"))),
        ("售后Excel行", "number", 14, lambda r: r.get("sourceRowNumber")),
        ("系统说明", "text", 42, lambda r: r.get("explanation")),
        ("建议动作", "text", 38, lambda r: r.get("suggestion")),
    ),
    "cost": (
        ("系统状态", "text", 18, lambda r: r.get("statusLabel")),
        *MANUAL_COLUMNS,
        ("子订单号", "text", 24, lambda r: r.get("subOrderId") or r.get("primaryIdentifier")),
        ("货号", "text", 20, lambda r: r.get("sku")),
        ("数量", "number", 12, lambda r: r.get("quantity")),
        ("单位成本", "money_cents", 16, lambda r: r.get("unitCostCents")),
        ("订单成本", "money_cents", 16, lambda r: r.get("totalCostCents")),
        ("订单金额", "money_cents", 16, lambda r: r.get("orderAmountCents")),
        ("订单Excel行", "number", 14, lambda r: r.get("sourceRowNumber")),
        ("成本Excel行", "number", 14, lambda r: r.get("linkedRowNumber")),
        ("系统说明", "text", 42, lambda r: r.get("explanation")),
        ("建议动作", "text", 42, lambda r: r.get("suggestion")),
    ),
    "other_fund": (
        ("系统状态", "text", 16, lambda r: r.get("statusLabel")),
        *MANUAL_COLUMNS,
        ("资金流水号", "text", 28, lambda r: r.get("transactionId") or r.get("primaryIdentifier")),
        ("子订单号", "text", 24, lambda r: r.get("subOrderId")),
        ("分类", "text", 22, lambda r: r.get("categoryLabel")),
        ("平台场景", "text", 30, lambda r: r.get("scene")),
        ("计费类型", "text", 22, lambda r: r.get("chargeType")),
        ("金额", "money_cents", 16, lambda r: r.get("amountCents")),
        ("动账时间", "datetime", 20, lambda r: r.get("eventTime")),
        ("资金Excel行", "number", 14, lambda r: r.get("sourceRowNumber")),
        ("备注", "text", 36, lambda r: r.get("remark")),
        ("系统说明", "text", 42, lambda r: r.get("explanation")),
        ("建议动作", "text", 42, lambda r: r.get("suggestion")),
    ),
}
