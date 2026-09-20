"""Build the unified reconciliation workbench without duplicating source facts."""

import json
import math
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


ATTENTION_STATUSES = {
    "missing_fund",
    "amount_mismatch",
    "multiple_candidates",
    "outside_auto_window",
    "not_calculable",
    "missing_historical_order",
    "missing_order_data",
    "multiple_history_orders",
    "settlement_receivable_mismatch",
    "settlement_receivable_not_calculable",
    "settlement_before_refund_review",
    "possibly_unsettled",
    "order_status_requires_review",
    "new_after_sale_status",
    "after_sale_refund_conflict",
    "refund_missing_after_sale",
    "missing_sku",
    "missing_cost",
    "multiple_cost_candidates",
    "waiting_classification",
}

RESULT_LABELS = {
    "matched": "核对一致",
    "missing_fund": "缺少资金记录",
    "amount_mismatch": "金额不一致",
    "multiple_candidates": "多笔候选",
    "outside_auto_window": "超出自动窗口",
    "not_calculable": "无法计算",
    "order_found_current": "本次订单已找到",
    "order_found_history": "历史订单已找到",
    "missing_historical_order": "缺少历史订单",
    "missing_order_data": "缺少订单资料",
    "multiple_history_orders": "多条历史订单",
    "settlement_receivable_mismatch": "订单应收与结算不符",
    "settlement_receivable_not_calculable": "订单应收无法计算",
    "settlement_before_refund_review": "结算前退款待核",
    "possibly_unsettled": "可能未结算",
    "order_status_requires_review": "订单状态待核",
    "normal_waiting": "正常等待结算",
    "fully_refunded_no_settlement": "全额退款无需结算",
    "closed_no_settlement": "已关闭无需结算",
    "refund_success": "退款成功",
    "after_sale_closed": "售后关闭",
    "exchange_success": "换货成功",
    "waiting_after_sale": "等待售后处理",
    "new_after_sale_status": "新售后状态",
    "after_sale_refund_conflict": "售后与退款冲突",
    "refund_missing_after_sale": "退款缺少售后单",
    "matched_static_cost": "静态成本已关联",
    "missing_sku": "缺少商品型号",
    "missing_cost": "缺少成本",
    "multiple_cost_candidates": "多条成本候选",
    "classified": "已分类",
    "waiting_classification": "等待分类",
}

RESULT_TYPE_LABELS = {
    "ordinary_settlement": "普通结算",
    "refund_settlement": "退款结算",
    "cross_month": "订单与结算",
    "after_sale": "售后",
    "cost": "成本",
    "other_fund": "其他收支",
}

STATUS_LABELS = {
    "needs_attention": "待处理",
    "matched": "核对一致",
    "resolved": "人工已处理",
    "carried_forward": "带到下月",
    "no_settlement": "未进入结算核对",
    "source_only": "仅有底表资料",
}


def build_wide_reconciliation_page(
    connection, task_id, file_id, status="all", scene="all", query="",
    page=1, page_size=50,
):
    file_row = connection.execute(
        """
        SELECT f.id, d.id AS import_id
        FROM file_versions f
        JOIN data_imports d ON d.file_version_id = f.id
        WHERE f.task_id = ? AND f.id = ?
        """,
        (task_id, file_id),
    ).fetchone()
    if file_row is None:
        return None

    records = connection.execute(
        """
        SELECT id, sheet_name, row_number, record_type, primary_identifier,
               secondary_identifier, event_time, amount_cents, raw_values_json
        FROM source_records
        WHERE import_id = ?
        ORDER BY row_number, id
        """,
        (file_row["import_id"],),
    ).fetchall()
    source_by_id = {record["id"]: record for record in records}
    entries = {}

    def ensure(key, sub_order_id=None):
        if key not in entries:
            entries[key] = _empty_entry(key, sub_order_id)
        elif sub_order_id and not entries[key]["subOrderId"]:
            entries[key]["subOrderId"] = sub_order_id
        return entries[key]

    for record in records:
        record_type = record["record_type"]
        if record_type == "cost":
            continue
        if record_type in ("order", "settlement"):
            sub_order_id = record["primary_identifier"]
        else:
            sub_order_id = record["secondary_identifier"]
        key = _entry_key(sub_order_id, record_type, record["primary_identifier"], record["id"])
        entry = ensure(key, sub_order_id)
        entry["sources"][record_type].append(_source_to_api(record))

    manual_map = _manual_resolution_map(connection, task_id, file_id)
    _attach_ordinary_results(connection, task_id, file_id, entries, ensure, manual_map)
    _attach_refund_results(connection, task_id, file_id, entries, ensure, manual_map)
    _attach_supplementary_results(
        connection, task_id, file_id, entries, ensure, manual_map, source_by_id
    )

    rows = [_finalize_entry(entry) for entry in entries.values()]
    rows.sort(key=_row_sort_key)
    normalized_query = " ".join(str(query or "").strip().split()).lower()
    scene_rows = [
        row for row in rows
        if (scene == "all" or scene in row["sceneKeys"])
        and (not normalized_query or _matches_query(row, normalized_query))
    ]
    summary = _summarize(scene_rows)
    if status != "all":
        filtered_rows = [row for row in scene_rows if _matches_status(row, status)]
    else:
        filtered_rows = scene_rows

    total_rows = len(filtered_rows)
    total_pages = max(1, int(math.ceil(total_rows / float(page_size))))
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * page_size
    page_rows = filtered_rows[offset:offset + page_size]
    return {
        "fileId": file_id,
        "resultType": "wide_reconciliation",
        "filter": status,
        "scene": scene,
        "query": query or "",
        "summary": summary,
        "pagination": {
            "page": page,
            "pageSize": page_size,
            "totalRows": total_rows,
            "totalPages": total_pages,
            "fromRow": offset + 1 if total_rows else 0,
            "toRow": min(offset + page_size, total_rows),
        },
        "rows": page_rows,
    }


def _empty_entry(key, sub_order_id):
    return {
        "rowKey": key,
        "subOrderId": sub_order_id or None,
        "sources": defaultdict(list),
        "results": [],
    }


def _entry_key(sub_order_id, record_type, primary_identifier, record_id):
    if sub_order_id:
        return "sub-order:{}".format(sub_order_id)
    return "{}:{}".format(record_type, primary_identifier or record_id)


def _source_to_api(record):
    return {
        "sourceRecordId": record["id"],
        "sheetName": record["sheet_name"],
        "rowNumber": record["row_number"],
        "primaryIdentifier": record["primary_identifier"],
        "secondaryIdentifier": record["secondary_identifier"],
        "eventTime": record["event_time"],
        "amountCents": record["amount_cents"],
        "values": _json_object(record["raw_values_json"]),
    }


def _manual_resolution_map(connection, task_id, file_id):
    rows = connection.execute(
        """
        SELECT result_type, result_id, resolution_state, action_type, reason,
               selected_candidate_key, adjusted_amount_cents, follow_up_date,
               created_at
        FROM manual_resolution_events
        WHERE task_id = ? AND file_version_id = ? AND is_current = 1
        """,
        (task_id, file_id),
    ).fetchall()
    return {
        (row["result_type"], row["result_id"]): {
            "resolutionState": row["resolution_state"],
            "resolutionStateLabel": (
                "已带到下月" if row["resolution_state"] == "carried_forward"
                else "人工已处理"
            ),
            "actionType": row["action_type"],
            "reason": row["reason"],
            "selectedCandidateKey": row["selected_candidate_key"],
            "adjustedAmountCents": row["adjusted_amount_cents"],
            "followUpDate": row["follow_up_date"],
            "createdAt": row["created_at"],
        }
        for row in rows
    }


def _attach_ordinary_results(connection, task_id, file_id, entries, ensure, manual_map):
    rows = connection.execute(
        """
        SELECT r.id, r.status, r.primary_identifier, r.settlement_record_id,
               r.fund_record_id, r.settlement_amount_cents, r.fund_amount_cents,
               r.difference_cents, r.explanation, r.suggestion
        FROM reconciliation_results r
        WHERE r.task_id = ? AND r.file_version_id = ?
        """,
        (task_id, file_id),
    ).fetchall()
    for row in rows:
        sub_order_id = row["primary_identifier"]
        entry = ensure(_entry_key(sub_order_id, "settlement", None, row["id"]), sub_order_id)
        entry["results"].append(_result_to_api(row, "ordinary_settlement", manual_map))


def _attach_refund_results(connection, task_id, file_id, entries, ensure, manual_map):
    rows = connection.execute(
        """
        SELECT r.id, r.status, r.primary_identifier, r.settlement_record_id,
               NULL AS fund_record_id, r.settlement_amount_cents,
               r.fund_net_amount_cents AS fund_amount_cents, r.difference_cents,
               r.after_sale_id, r.explanation, r.suggestion
        FROM refund_reconciliation_results r
        WHERE r.task_id = ? AND r.file_version_id = ?
        """,
        (task_id, file_id),
    ).fetchall()
    for row in rows:
        sub_order_id = row["primary_identifier"]
        entry = ensure(_entry_key(sub_order_id, "settlement", None, row["id"]), sub_order_id)
        item = _result_to_api(row, "refund_settlement", manual_map)
        item["afterSaleId"] = row["after_sale_id"]
        entry["results"].append(item)


def _attach_supplementary_results(
    connection, task_id, file_id, entries, ensure, manual_map, source_by_id
):
    rows = connection.execute(
        """
        SELECT r.id, r.result_type, r.status, r.primary_identifier,
               r.source_record_id, r.linked_source_record_id,
               r.amount_cents, r.calculated_amount_cents,
               r.metadata_json, r.explanation, r.suggestion
        FROM supplementary_reconciliation_results r
        JOIN supplementary_reconciliation_runs srr ON srr.id = r.run_id
        WHERE r.task_id = ? AND r.file_version_id = ? AND srr.is_current = 1
        """,
        (task_id, file_id),
    ).fetchall()
    for row in rows:
        metadata = _json_object(row["metadata_json"])
        result_type = row["result_type"]
        sub_order_id = metadata.get("subOrderId")
        if not sub_order_id and result_type in ("cross_month", "cost"):
            sub_order_id = row["primary_identifier"]
        if not sub_order_id and result_type == "after_sale":
            sub_order_id = metadata.get("subOrderId")
        if sub_order_id:
            key = _entry_key(sub_order_id, result_type, row["primary_identifier"], row["id"])
        else:
            source = source_by_id.get(row["source_record_id"])
            source_primary = source["primary_identifier"] if source else row["primary_identifier"]
            source_type = source["record_type"] if source else result_type
            source_id = source["id"] if source else row["id"]
            key = _entry_key(None, source_type, source_primary, source_id)
        entry = ensure(key, sub_order_id)
        item = _result_to_api(row, result_type, manual_map)
        item.update(metadata)
        entry["results"].append(item)


def _result_to_api(row, result_type, manual_map):
    status = row["status"]
    return {
        "id": row["id"],
        "resultType": result_type,
        "resultTypeLabel": RESULT_TYPE_LABELS[result_type],
        "status": status,
        "statusLabel": RESULT_LABELS.get(status, status),
        "isAttention": status in ATTENTION_STATUSES,
        "settlementAmountCents": _row_value(row, "settlement_amount_cents"),
        "fundAmountCents": _row_value(row, "fund_amount_cents"),
        "differenceCents": _row_value(row, "difference_cents"),
        "amountCents": _row_value(row, "amount_cents"),
        "calculatedAmountCents": _row_value(row, "calculated_amount_cents"),
        "explanation": row["explanation"],
        "suggestion": row["suggestion"],
        "manualResolution": manual_map.get((result_type, row["id"])),
    }


def _finalize_entry(entry):
    sources = entry["sources"]
    order_sources = sources.get("order", [])
    after_sale_sources = sources.get("after_sale", [])
    settlement_sources = sources.get("settlement", [])
    fund_sources = sources.get("fund", [])
    order = order_sources[0] if order_sources else None
    raw_order = order["values"] if order else {}

    result_types = []
    for result in entry["results"]:
        if result["resultType"] not in result_types:
            result_types.append(result["resultType"])
    scene_labels = [RESULT_TYPE_LABELS[item] for item in result_types]
    if not result_types:
        if settlement_sources:
            result_types.append("ordinary_settlement")
            scene_labels.append("结算资料")
        elif after_sale_sources:
            result_types.append("after_sale")
            scene_labels.append("售后资料")
        else:
            result_types.append("order_only")
            scene_labels.append("订单资料")

    unresolved = [
        result for result in entry["results"]
        if result["isAttention"] and not result["manualResolution"]
    ]
    carried = [
        result for result in entry["results"]
        if result["manualResolution"]
        and result["manualResolution"]["resolutionState"] == "carried_forward"
    ]
    resolved = [
        result for result in entry["results"]
        if result["manualResolution"]
        and result["manualResolution"]["resolutionState"] == "resolved"
    ]
    matched = [
        result for result in entry["results"]
        if result["resultType"] in ("ordinary_settlement", "refund_settlement")
        and result["status"] == "matched"
    ]
    if unresolved:
        overall_status = "needs_attention"
        primary = unresolved[0]
    elif carried:
        overall_status = "carried_forward"
        primary = carried[0]
    elif resolved:
        overall_status = "resolved"
        primary = resolved[0]
    elif matched:
        overall_status = "matched"
        primary = matched[0]
    elif result_types == ["other_fund"]:
        overall_status = "source_only"
        primary = entry["results"][0] if entry["results"] else None
    elif not settlement_sources:
        overall_status = "no_settlement"
        primary = entry["results"][0] if entry["results"] else None
    else:
        overall_status = "source_only"
        primary = entry["results"][0] if entry["results"] else None

    result_differences = [
        result["differenceCents"] for result in entry["results"]
        if result["resultType"] in ("ordinary_settlement", "refund_settlement")
        and result["differenceCents"] is not None
    ]
    receivable_differences = [
        result["receivableDifferenceCents"] for result in entry["results"]
        if result.get("resultType") == "cross_month"
        and result.get("receivableDifferenceCents") is not None
    ]
    platform_discount = _money_to_cents(raw_order.get("平台实际承担优惠金额"))
    creator_discount = _money_to_cents(raw_order.get("达人实际承担优惠金额"))
    merchant_discount = _money_to_cents(raw_order.get("商家实际承担优惠金额"))
    order_amount = order["amountCents"] if order else None
    expected_receivable = None
    if order_amount is not None:
        expected_receivable = order_amount + (platform_discount or 0) + (creator_discount or 0)

    after_sale_requested_refund = sum(item["amountCents"] or 0 for item in after_sale_sources)
    after_sale_successful_refund = sum(
        item["amountCents"] or 0 for item in after_sale_sources
        if "退款成功" in str(item["values"].get("售后状态") or "")
    )
    settlement_net = sum(item["amountCents"] or 0 for item in settlement_sources)
    settlement_income = sum(
        _money_to_cents(item["values"].get("收入合计")) or 0
        for item in settlement_sources
    )
    settlement_expense = sum(
        _money_to_cents(item["values"].get("支出合计")) or 0
        for item in settlement_sources
    )
    fund_net = sum(item["amountCents"] or 0 for item in fund_sources)

    cost_results = [item for item in entry["results"] if item["resultType"] == "cost"]
    cost_result = cost_results[0] if cost_results else None
    source_rows = []
    for source_type in ("order", "after_sale", "settlement", "fund"):
        for source in sources.get(source_type, []):
            source_rows.append({
                "sheetName": source["sheetName"],
                "rowNumber": source["rowNumber"],
                "primaryIdentifier": source["primaryIdentifier"],
                "eventTime": source["eventTime"],
                "amountCents": source["amountCents"],
            })

    reason = ""
    suggestion = ""
    if primary:
        manual = primary.get("manualResolution")
        reason = manual.get("reason") if manual else primary.get("explanation")
        suggestion = (
            manual.get("resolutionStateLabel") if manual else primary.get("suggestion")
        )
    elif not settlement_sources:
        reason = "当前文件没有这个子订单的结算记录。"
        suggestion = "保留订单资料；是否到期需结合平台预计结算日判断。"

    return {
        "rowKey": entry["rowKey"],
        "status": overall_status,
        "statusLabel": STATUS_LABELS[overall_status],
        "sceneKeys": result_types,
        "sceneLabels": scene_labels,
        "reason": reason or "—",
        "suggestion": suggestion or "—",
        "primaryResult": primary,
        "resultCount": len(entry["results"]),
        "unresolvedCount": len(unresolved),
        "manualResolvedCount": len(resolved),
        "subOrderId": entry["subOrderId"],
        "mainOrderId": raw_order.get("主订单编号"),
        "sku": raw_order.get("货号"),
        "quantity": _number(raw_order.get("商品数量")),
        "orderStatus": raw_order.get("订单状态"),
        "orderType": raw_order.get("订单类型"),
        "submittedAt": order["eventTime"] if order else None,
        "unitPriceCents": _money_to_cents(raw_order.get("商品金额")),
        "shippingCents": _money_to_cents(raw_order.get("运费")),
        "orderPayableCents": order_amount,
        "platformDiscountCents": platform_discount,
        "merchantDiscountCents": merchant_discount,
        "creatorDiscountCents": creator_discount,
        "expectedMerchantReceivableCents": expected_receivable,
        "afterSaleCount": len(after_sale_sources),
        "afterSaleIds": [item["primaryIdentifier"] for item in after_sale_sources],
        "afterSaleTypes": _distinct_values(after_sale_sources, "售后类型"),
        "afterSaleStatuses": _distinct_values(after_sale_sources, "售后状态"),
        "afterSaleRequestedRefundCents": after_sale_requested_refund if after_sale_sources else None,
        "afterSaleRefundCents": after_sale_successful_refund if after_sale_sources else None,
        "afterSaleLatestAt": _latest_time(after_sale_sources),
        "settlementCount": len(settlement_sources),
        "settlementTypes": _distinct_values(settlement_sources, "结算单类型"),
        "settlementLatestAt": _latest_time(settlement_sources),
        "settlementIncomeCents": settlement_income if settlement_sources else None,
        "settlementExpenseCents": settlement_expense if settlement_sources else None,
        "settlementNetCents": settlement_net if settlement_sources else None,
        "fundCount": len(fund_sources),
        "fundScenes": _distinct_values(fund_sources, "动账场景"),
        "fundLatestAt": _latest_time(fund_sources),
        "fundTransactionIds": [item["primaryIdentifier"] for item in fund_sources],
        "fundNetCents": fund_net if fund_sources else None,
        "differenceCents": sum(result_differences) if result_differences else None,
        "receivableDifferenceCents": sum(receivable_differences) if receivable_differences else None,
        "costStatus": cost_result["statusLabel"] if cost_result else "未关联",
        "unitCostCents": cost_result.get("unitCostCents") if cost_result else None,
        "totalCostCents": cost_result.get("totalCostCents") if cost_result else None,
        "sourceRows": source_rows,
        "results": entry["results"],
    }


def _summarize(rows):
    status_counts = defaultdict(int)
    for row in rows:
        status_counts[row["status"]] += 1
    return {
        "totalRowCount": len(rows),
        "attentionCount": status_counts["needs_attention"],
        "matchedCount": status_counts["matched"],
        "resolvedCount": status_counts["resolved"],
        "carriedForwardCount": status_counts["carried_forward"],
        "noSettlementCount": status_counts["no_settlement"],
        "settlementNetTotalCents": sum(row["settlementNetCents"] or 0 for row in rows),
        "fundNetTotalCents": sum(row["fundNetCents"] or 0 for row in rows),
        "statusCounts": dict(status_counts),
    }


def _matches_status(row, status):
    if status == "resolved":
        return row["status"] in ("resolved", "carried_forward")
    return row["status"] == status


def _matches_query(row, query):
    values = [
        row.get("subOrderId"), row.get("mainOrderId"), row.get("sku"),
        *row.get("afterSaleIds", []), *row.get("fundTransactionIds", []),
    ]
    return query in " ".join(str(value).lower() for value in values if value)


def _row_sort_key(row):
    status_order = {
        "needs_attention": 0,
        "carried_forward": 1,
        "resolved": 2,
        "no_settlement": 3,
        "source_only": 4,
        "matched": 5,
    }
    return (
        status_order.get(row["status"], 9),
        row.get("submittedAt") or row.get("settlementLatestAt") or "",
        row.get("subOrderId") or row["rowKey"],
    )


def _distinct_values(sources, field_name):
    result = []
    for source in sources:
        value = source["values"].get(field_name)
        if value not in (None, "") and value not in result:
            result.append(value)
    return result


def _latest_time(sources):
    values = [source["eventTime"] for source in sources if source["eventTime"]]
    return max(values) if values else None


def _json_object(value):
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _money_to_cents(value):
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return int((number * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _number(value):
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return int(number) if number == number.to_integral() else float(number)


def _row_value(row, key):
    return row[key] if key in row.keys() else None
