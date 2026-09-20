import json
from collections import Counter, defaultdict

from .data_import import (
    normalize_identifier,
    normalize_text,
    parse_excel_datetime,
    parse_money_or_number,
)
from .xlsx import extract_defined_workbook_rows, inspect_defined_workbook


MAPPING_VERSION = "M017-SIM-1"
PLATFORM_BALANCE_SHEETS = (
    {
        "name": "资金流水明细",
        "header_row": 5,
        "data_start_row": 6,
        "required_headers": (
            "动账时间", "动帐流水号", "动账方向", "动账金额", "动账账户",
        ),
    },
    {
        "name": "资金日汇总",
        "header_row": 5,
        "data_start_row": 6,
        "required_headers": (
            "测试账户", "日期", "明细笔数", "总收入", "总支出",
            "余额变化", "期初余额", "期末余额",
        ),
    },
    {
        "name": "资金月汇总",
        "header_row": 5,
        "data_start_row": 6,
        "required_headers": (
            "测试账户", "日期（月）", "明细笔数", "总收入", "总支出",
            "余额变化", "期初余额", "期末余额",
        ),
    },
)


def inspect_platform_balance_workbook(file_path):
    inspected = inspect_defined_workbook(file_path, PLATFORM_BALANCE_SHEETS)
    inspected["mappingVersion"] = MAPPING_VERSION
    inspected["trialMode"] = True
    inspected["mappingNotice"] = (
        "当前按M017模拟字段映射检查；取得抖店真实日/月汇总后再冻结生产表头。"
    )
    return inspected


def calculate_platform_balance(file_path, task_period, tolerance_cents=1):
    if tolerance_cents is None or tolerance_cents < 0:
        raise ValueError("金额容差不能小于0")
    workbook_rows = extract_defined_workbook_rows(
        file_path, PLATFORM_BALANCE_SHEETS
    )
    source_rows = []
    invalid_results = []
    detail_rows = []
    day_rows = []
    month_rows = []

    for source in workbook_rows.get("资金流水明细", []):
        parsed, errors = _parse_detail(source)
        source_rows.append(_source_row("fund_detail", "资金流水明细", source))
        if errors:
            invalid_results.append(_invalid_result("资金流水明细", source, errors))
        else:
            detail_rows.append(parsed)
    for source in workbook_rows.get("资金日汇总", []):
        parsed, errors = _parse_summary(source, "day")
        source_rows.append(_source_row("day_summary", "资金日汇总", source))
        if errors:
            invalid_results.append(_invalid_result("资金日汇总", source, errors))
        else:
            day_rows.append(parsed)
    for source in workbook_rows.get("资金月汇总", []):
        parsed, errors = _parse_summary(source, "month")
        source_rows.append(_source_row("month_summary", "资金月汇总", source))
        if errors:
            invalid_results.append(_invalid_result("资金月汇总", source, errors))
        else:
            month_rows.append(parsed)

    duplicate_transactions = defaultdict(list)
    for item in detail_rows:
        duplicate_transactions[item["transactionId"]].append(item)
    for transaction_id, duplicated in duplicate_transactions.items():
        if transaction_id and len(duplicated) > 1:
            invalid_results.append({
                "level": "source",
                "status": "invalid_source",
                "batchKey": duplicated[0]["batchKey"],
                "account": duplicated[0]["account"],
                "periodKey": duplicated[0]["date"],
                "sourceSheet": "资金流水明细",
                "sourceRowNumber": duplicated[0]["rowNumber"],
                "summaryCount": None,
                "detailCount": len(duplicated),
                "summaryIncomeCents": None,
                "detailIncomeCents": None,
                "summaryExpenseCents": None,
                "detailExpenseCents": None,
                "openingBalanceCents": None,
                "closingBalanceCents": None,
                "calculatedClosingBalanceCents": None,
                "differenceCents": None,
                "metadata": {"transactionId": transaction_id},
                "explanation": "资金流水号重复，无法证明逐笔明细唯一完整。",
                "suggestion": "回到平台原文件核对重复流水，修正后重新导入。",
            })

    results = []
    results.extend(_calculate_day_results(detail_rows, day_rows, task_period, tolerance_cents))
    results.extend(_calculate_month_results(detail_rows, day_rows, month_rows, task_period, tolerance_cents))
    results.extend(invalid_results)
    status_counts = dict(Counter(item["status"] for item in results))
    attention_count = sum(item["status"] != "matched" for item in results)
    return {
        "mappingVersion": MAPPING_VERSION,
        "trialMode": True,
        "enforcementMode": "informational",
        "resultType": "platform_balance",
        "resultLabel": "平台账户完整性",
        "taskPeriod": task_period,
        "toleranceCents": tolerance_cents,
        "status": "needs_attention" if attention_count else "passed",
        "totalResultCount": len(results),
        "matchedCount": len(results) - attention_count,
        "attentionCount": attention_count,
        "dayResultCount": sum(item["level"] == "day" for item in results),
        "monthResultCount": sum(item["level"] == "month" for item in results),
        "dateGapCount": sum(item.get("metadata", {}).get("checkType") == "date_gap" for item in results),
        "statusCounts": status_counts,
        "sourceRowCount": len(source_rows),
        "sourceRows": source_rows,
        "results": results,
    }


def _calculate_day_results(details, summaries, task_period, tolerance):
    detail_groups = defaultdict(list)
    for item in details:
        detail_groups[(item["batchKey"], item["account"], item["date"])].append(item)
    summary_keys = set()
    results = []
    for summary in sorted(summaries, key=lambda item: (item["batchKey"], item["account"], item["periodKey"], item["rowNumber"])):
        key = (summary["batchKey"], summary["account"], summary["periodKey"])
        summary_keys.add(key)
        matched_details = detail_groups.get(key, [])
        results.append(_compare_summary(summary, matched_details, task_period, tolerance))

    for key, matched_details in sorted(detail_groups.items()):
        if key in summary_keys:
            continue
        first = matched_details[0]
        totals = _detail_totals(matched_details)
        results.append({
            "level": "day",
            "status": "detail_incomplete",
            "batchKey": first["batchKey"],
            "account": first["account"],
            "periodKey": first["date"],
            "sourceSheet": "资金流水明细",
            "sourceRowNumber": first["rowNumber"],
            "summaryCount": None,
            "detailCount": totals["count"],
            "summaryIncomeCents": None,
            "detailIncomeCents": totals["incomeCents"],
            "summaryExpenseCents": None,
            "detailExpenseCents": totals["expenseCents"],
            "openingBalanceCents": None,
            "closingBalanceCents": None,
            "calculatedClosingBalanceCents": None,
            "differenceCents": None,
            "metadata": {"checkType": "date_gap"},
            "explanation": "逐笔资金存在{}的交易，但资金日汇总缺少该日，月汇总一致也不能证明每日资料完整。".format(first["date"]),
            "suggestion": "补充该日汇总，或记录平台明确的日汇总导出规则后重新核对。",
        })
    return results


def _calculate_month_results(details, day_summaries, month_summaries, task_period, tolerance):
    detail_groups = defaultdict(list)
    for item in details:
        detail_groups[(item["batchKey"], item["account"], item["month"])].append(item)
    results = []
    for summary in sorted(month_summaries, key=lambda item: (item["batchKey"], item["account"], item["periodKey"], item["rowNumber"])):
        key = (summary["batchKey"], summary["account"], summary["periodKey"])
        results.append(
            _compare_summary(summary, detail_groups.get(key, []), task_period, tolerance)
        )
    return results


def _compare_summary(summary, details, task_period, tolerance):
    totals = _detail_totals(details)
    count_difference = totals["count"] - summary["count"]
    income_difference = totals["incomeCents"] - summary["incomeCents"]
    expense_difference = totals["expenseCents"] - summary["expenseCents"]
    expected_change = summary["incomeCents"] - summary["expenseCents"]
    balance_change_difference = summary["balanceChangeCents"] - expected_change
    calculated_closing = summary["openingBalanceCents"] + summary["balanceChangeCents"]
    closing_difference = summary["closingBalanceCents"] - calculated_closing
    reasons = []
    if count_difference:
        reasons.append("明细笔数相差{}笔".format(count_difference))
    if abs(income_difference) > tolerance:
        reasons.append("收入相差{}".format(_money(income_difference)))
    if abs(expense_difference) > tolerance:
        reasons.append("支出相差{}".format(_money(expense_difference)))
    if abs(balance_change_difference) > tolerance:
        reasons.append("余额变化公式相差{}".format(_money(balance_change_difference)))
    if abs(closing_difference) > tolerance:
        reasons.append("期末余额公式相差{}".format(_money(closing_difference)))

    period_mismatch = summary["periodKey"][:7] != task_period
    account_missing = not details
    if period_mismatch or account_missing:
        status = "account_period_mismatch"
        if period_mismatch:
            explanation = "汇总月份{}与任务月份{}不一致。".format(summary["periodKey"][:7], task_period)
            suggestion = "选择正确月份的汇总文件后重新导入。"
        else:
            explanation = "汇总账户{}没有对应的逐笔资金流水。".format(summary["account"])
            suggestion = "选择正确账户，或补充该账户的逐笔资金流水。"
    elif reasons:
        status = "detail_incomplete"
        explanation = "；".join(reasons) + "，逐笔资金或汇总口径可能不完整。"
        suggestion = "回到平台原文件检查漏行、重复合并、金额方向和余额口径。"
    else:
        status = "matched"
        explanation = "汇总笔数、收入、支出、余额变化和期初期末均与逐笔资金一致。"
        suggestion = "无需处理。"
    return {
        "level": summary["level"],
        "status": status,
        "batchKey": summary["batchKey"],
        "account": summary["account"],
        "periodKey": summary["periodKey"],
        "sourceSheet": summary["sheetName"],
        "sourceRowNumber": summary["rowNumber"],
        "summaryCount": summary["count"],
        "detailCount": totals["count"],
        "summaryIncomeCents": summary["incomeCents"],
        "detailIncomeCents": totals["incomeCents"],
        "summaryExpenseCents": summary["expenseCents"],
        "detailExpenseCents": totals["expenseCents"],
        "openingBalanceCents": summary["openingBalanceCents"],
        "closingBalanceCents": summary["closingBalanceCents"],
        "calculatedClosingBalanceCents": calculated_closing,
        "differenceCents": max(
            (income_difference, expense_difference, balance_change_difference, closing_difference),
            key=abs,
        ),
        "metadata": {
            "countDifference": count_difference,
            "incomeDifferenceCents": income_difference,
            "expenseDifferenceCents": expense_difference,
            "balanceChangeDifferenceCents": balance_change_difference,
            "closingDifferenceCents": closing_difference,
        },
        "explanation": explanation,
        "suggestion": suggestion,
    }


def _parse_detail(source):
    values = source["values"]
    errors = []
    batch = normalize_text(values.get("测试批次")) or "CURRENT"
    account = normalize_text(values.get("动账账户"))
    transaction_id = normalize_identifier(values.get("动帐流水号"))
    direction = normalize_text(values.get("动账方向"))
    event_time, date_error = parse_excel_datetime(values.get("动账时间"))
    amount_cents, amount_error = parse_money_or_number(values.get("动账金额"), cents=True)
    if not account:
        errors.append("动账账户为空")
    if not transaction_id:
        errors.append("动账流水号为空")
    if direction not in ("入账", "出账"):
        errors.append("动账方向必须是入账或出账")
    if date_error:
        errors.append(date_error)
    if amount_error:
        errors.append(amount_error)
    return ({
        "batchKey": batch,
        "account": account,
        "transactionId": transaction_id,
        "direction": direction,
        "amountCents": abs(amount_cents or 0),
        "eventTime": event_time,
        "date": event_time[:10] if event_time else None,
        "month": event_time[:7] if event_time else None,
        "rowNumber": source["rowNumber"],
    }, errors)


def _parse_summary(source, level):
    values = source["values"]
    errors = []
    date_field = "日期" if level == "day" else "日期（月）"
    event_time, date_error = parse_excel_datetime(values.get(date_field))
    count, count_error = parse_money_or_number(values.get("明细笔数"), cents=False)
    parsed = {}
    for field, key in (
        ("总收入", "incomeCents"),
        ("总支出", "expenseCents"),
        ("余额变化", "balanceChangeCents"),
        ("期初余额", "openingBalanceCents"),
        ("期末余额", "closingBalanceCents"),
    ):
        parsed[key], error = parse_money_or_number(values.get(field), cents=True)
        if error:
            errors.append("{}{}".format(field, error))
    account = normalize_text(values.get("测试账户"))
    if not account:
        errors.append("测试账户为空")
    if date_error:
        errors.append(date_error)
    if count_error:
        errors.append("明细笔数{}".format(count_error))
    return ({
        "level": level,
        "sheetName": "资金日汇总" if level == "day" else "资金月汇总",
        "batchKey": normalize_text(values.get("测试批次")) or "CURRENT",
        "account": account,
        "periodKey": (event_time[:10] if level == "day" else event_time[:7]) if event_time else None,
        "count": count or 0,
        "rowNumber": source["rowNumber"],
        **{key: value or 0 for key, value in parsed.items()},
    }, errors)


def _detail_totals(items):
    return {
        "count": len(items),
        "incomeCents": sum(item["amountCents"] for item in items if item["direction"] == "入账"),
        "expenseCents": sum(item["amountCents"] for item in items if item["direction"] == "出账"),
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
        "level": "source",
        "status": "invalid_source",
        "batchKey": normalize_text(values.get("测试批次")) or "CURRENT",
        "account": normalize_text(values.get("动账账户") or values.get("测试账户")) or None,
        "periodKey": None,
        "sourceSheet": sheet_name,
        "sourceRowNumber": source["rowNumber"],
        "summaryCount": None,
        "detailCount": None,
        "summaryIncomeCents": None,
        "detailIncomeCents": None,
        "summaryExpenseCents": None,
        "detailExpenseCents": None,
        "openingBalanceCents": None,
        "closingBalanceCents": None,
        "calculatedClosingBalanceCents": None,
        "differenceCents": None,
        "metadata": {"errors": errors},
        "explanation": "源数据无法计算：{}。".format("；".join(errors)),
        "suggestion": "修正对应Excel行后重新导入。",
    }


def _money(cents):
    prefix = "-" if cents < 0 else ""
    return "{}¥{:,.2f}".format(prefix, abs(cents) / 100)
