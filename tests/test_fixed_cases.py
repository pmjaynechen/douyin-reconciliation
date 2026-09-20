import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from recon_app.amount_checks import calculate_amount_checks
from recon_app.data_import import analyze_workbook_data
from recon_app.refund_reconciliation import calculate_refund_settlement_reconciliation
from recon_app.settlement_reconciliation import calculate_ordinary_settlement_reconciliation
from recon_app.supplementary_reconciliation import (
    calculate_supplementary_reconciliation,
    classify_expected_settlement,
)
from xlsx_fixture import DEFAULT_ROWS, build_workbook_bytes


class FixedCaseTests(unittest.TestCase):
    rule_parameters = {
        "tolerance_cents": 1,
        "refund_auto_group_seconds": 300,
        "refund_candidate_seconds": 86400,
        "settlement_wait_days": 7,
    }

    @classmethod
    def setUpClass(cls):
        cls.tolerance_cents = cls.rule_parameters["tolerance_cents"]
        cls.auto_group_seconds = cls.rule_parameters["refund_auto_group_seconds"]
        cls.candidate_seconds = cls.rule_parameters["refund_candidate_seconds"]
        cls.wait_days = cls.rule_parameters["settlement_wait_days"]
        project_root = Path(__file__).resolve().parents[3]
        workbook_path = project_root / "对账文件" / "抖店练习数据.xlsx"
        cls.imported = analyze_workbook_data(workbook_path, "2023-12")
        cls.amount_checks = calculate_amount_checks(
            cls.imported["records"], cls.tolerance_cents
        )
        cls.ordinary = calculate_ordinary_settlement_reconciliation(
            cls.imported["records"], cls.tolerance_cents
        )
        cls.refunds = calculate_refund_settlement_reconciliation(
            cls.imported["records"], cls.tolerance_cents,
            cls.auto_group_seconds, cls.candidate_seconds
        )
        cls.supplementary = calculate_supplementary_reconciliation(
            cls.imported["records"], [], cls.wait_days,
            tolerance_cents=cls.tolerance_cents,
        )

    def test_c01_real_order_amount_baseline(self):
        summary = self._amount_summary("R01_ORDER_PAYABLE")
        self.assertEqual(summary["passedCount"], 2435)
        self.assertEqual(summary["failedCount"], 0)

    def test_c02_real_settlement_amount_baseline(self):
        for code in (
            "R02_ORDER_TOTAL",
            "R02_INCOME_TOTAL",
            "R02_EXPENSE_TOTAL",
            "R02_SETTLEMENT_AMOUNT",
        ):
            with self.subTest(code=code):
                summary = self._amount_summary(code)
                self.assertEqual(summary["passedCount"], 381)
                self.assertEqual(summary["failedCount"], 0)

    def test_c03_real_ordinary_settlement_baseline(self):
        self.assertEqual(self.ordinary["matchedCount"], 375)
        self.assertEqual(self.ordinary["attentionCount"], 0)
        self.assertEqual(self.ordinary["settlementAmountTotalCents"], 58884824)
        self.assertEqual(self.ordinary["differenceTotalCents"], 0)

    def test_c04_real_refund_settlement_baseline(self):
        self.assertEqual(self.refunds["matchedCount"], 6)
        self.assertEqual(self.refunds["attentionCount"], 0)
        self.assertEqual(self.refunds["settlementAmountTotalCents"], -1158760)
        self.assertEqual(self.refunds["differenceTotalCents"], 0)

    def test_c05_missing_history_is_not_platform_underpayment(self):
        cross_month = self.supplementary["crossMonth"]
        self.assertEqual(cross_month["missingHistoricalOrderCount"], 114)
        missing = [
            item for item in cross_month["results"]
            if item["status"] == "missing_historical_order"
        ]
        self.assertTrue(missing)
        self.assertTrue(all("不是平台少结" in item["explanation"] for item in missing))

    def test_c06_multiple_after_sales_are_preserved(self):
        after_sales = self.supplementary["afterSales"]
        self.assertEqual(after_sales["multipleAfterSaleOrderCount"], 14)
        self.assertEqual(after_sales["totalResultCount"], 212)

    def test_c07_closed_after_sales_are_not_refunds(self):
        after_sales = self.supplementary["afterSales"]
        self.assertEqual(after_sales["closedCount"], 28)
        closed = [
            item for item in after_sales["results"]
            if item["status"] == "after_sale_closed"
        ]
        self.assertTrue(all("不能当作退款" in item["explanation"] for item in closed))

    def test_c08_missing_sku_does_not_calculate_cost(self):
        costs = self.supplementary["costs"]
        self.assertEqual(costs["missingSkuCount"], 1)
        missing = next(item for item in costs["results"] if item["status"] == "missing_sku")
        self.assertIsNone(missing["totalCostCents"])

    def test_c09_duplicate_fund_identifier_blocks_import(self):
        rows = _copy_default_rows()
        duplicate = dict(rows["资金账单"][0])
        rows["资金账单"] = (rows["资金账单"][0], duplicate)
        imported = _analyze_fixture(rows)
        duplicate_issues = [
            item for item in imported["issues"]
            if item["code"] == "duplicate_identifier" and item["sheetName"] == "资金账单"
        ]
        self.assertEqual(imported["status"], "failed")
        self.assertEqual(len(duplicate_issues), 2)

    def test_c10_multiple_refund_groups_stop_automatic_choice(self):
        result = calculate_refund_settlement_reconciliation(
            [
                _refund_settlement(),
                _refund_fund(4, "AFTER1", "2023-12-01T10:00:01"),
                _refund_fund(5, "AFTER2", "2023-12-01T10:00:02"),
            ],
            self.tolerance_cents,
            self.auto_group_seconds,
            self.candidate_seconds,
        )
        self.assertEqual(result["results"][0]["status"], "multiple_candidates")
        self.assertEqual(result["results"][0]["matchedCandidateCount"], 2)

    def test_c11_unknown_fund_waits_for_classification(self):
        result = calculate_supplementary_reconciliation(
            [_other_fund("未配置的平台费用", -500, "新的费用名称")], [], self.wait_days
        )
        row = result["otherFunds"]["results"][0]
        self.assertEqual(row["status"], "waiting_classification")
        self.assertEqual(row["category"], "waiting_classification")

    def test_c12_withdrawal_is_not_bank_receipt(self):
        other_funds = self.supplementary["otherFunds"]
        self.assertEqual(other_funds["categoryCounts"]["withdrawal"], 9)
        withdrawals = [
            item for item in other_funds["results"] if item["category"] == "withdrawal"
        ]
        self.assertTrue(all("不代表企业银行已经到账" in item["explanation"] for item in withdrawals))

    def test_c13_difference_at_tolerance_passes(self):
        rows = _copy_default_rows()
        rows["资金账单"][0]["动账金额"] = _money_with_difference(
            self.tolerance_cents
        )
        result = _ordinary_from_fixture(rows, self.tolerance_cents)
        self.assertEqual(result["toleranceCents"], self.tolerance_cents)
        self.assertEqual(result["results"][0]["status"], "matched")
        self.assertEqual(
            result["results"][0]["differenceCents"], self.tolerance_cents
        )

    def test_c14_difference_above_tolerance_needs_attention(self):
        rows = _copy_default_rows()
        rows["资金账单"][0]["动账金额"] = _money_with_difference(
            self.tolerance_cents + 1
        )
        result = _ordinary_from_fixture(rows, self.tolerance_cents)
        self.assertEqual(result["results"][0]["status"], "amount_mismatch")
        self.assertEqual(
            result["results"][0]["differenceCents"], self.tolerance_cents + 1
        )

    def test_c15_refund_inside_auto_window_is_automatically_grouped(self):
        result = calculate_refund_settlement_reconciliation(
            [
                _refund_settlement(),
                _refund_fund(4, "AFTER1", _time_after(self.auto_group_seconds - 1)),
                _successful_after_sale(),
            ],
            self.tolerance_cents,
            self.auto_group_seconds,
            self.candidate_seconds,
        )
        self.assertEqual(result["results"][0]["status"], "matched")
        self.assertEqual(
            result["results"][0]["maxTimeDifferenceSeconds"],
            self.auto_group_seconds - 1,
        )

    def test_c16_refund_outside_auto_window_is_candidate_only(self):
        result = calculate_refund_settlement_reconciliation(
            [
                _refund_settlement(),
                _refund_fund(4, "AFTER1", _time_after(self.auto_group_seconds + 1)),
            ],
            self.tolerance_cents,
            self.auto_group_seconds,
            self.candidate_seconds,
        )
        self.assertEqual(result["results"][0]["status"], "outside_auto_window")
        self.assertEqual(
            result["results"][0]["maxTimeDifferenceSeconds"],
            self.auto_group_seconds + 1,
        )

    def test_c17_wait_day_boundary(self):
        completed = datetime.fromisoformat("2023-12-01T10:00:00")
        boundary = classify_expected_settlement(
            (completed + timedelta(days=self.wait_days)).isoformat(),
            completed_at="2023-12-01T10:00:00",
            settlement_wait_days=self.wait_days,
        )
        overdue = classify_expected_settlement(
            (completed + timedelta(days=self.wait_days, seconds=1)).isoformat(),
            completed_at="2023-12-01T10:00:00",
            settlement_wait_days=self.wait_days,
        )
        self.assertEqual(boundary["status"], "normal_waiting")
        self.assertEqual(overdue["status"], "possibly_unsettled")

    def test_c18_open_after_sale_precedes_overdue(self):
        result = classify_expected_settlement(
            "2023-12-09T10:00:00",
            platform_expected_at="2023-12-08T10:00:00",
            has_open_after_sale=True,
            settlement_wait_days=self.wait_days,
        )
        self.assertEqual(result["status"], "waiting_after_sale")
        self.assertIn("不判断平台逾期", result["explanation"])

    def test_c19_order_receivable_mismatch_needs_attention(self):
        result = calculate_supplementary_reconciliation(
            [
                {
                    "sourceRecordId": 1, "recordType": "order", "rowNumber": 2,
                    "primaryIdentifier": "SUB1", "amountCents": 1000,
                    "eventTime": "2023-12-01T10:00:00",
                    "rawValuesJson": {
                        "平台实际承担优惠金额": 0,
                        "达人实际承担优惠金额": 0,
                    },
                },
                {
                    "sourceRecordId": 2, "recordType": "settlement", "rowNumber": 3,
                    "primaryIdentifier": "SUB1", "amountCents": 100,
                    "rawValuesJson": {"结算单类型": "已结算", "收入合计": "1.00"},
                },
            ], [], self.wait_days, task_period="2023-12",
            tolerance_cents=self.tolerance_cents,
        )
        self.assertEqual(result["crossMonth"]["receivableMismatchCount"], 1)

    def test_c20_overdue_completed_order_without_settlement_needs_attention(self):
        result = calculate_supplementary_reconciliation(
            [{
                "sourceRecordId": 1, "recordType": "order", "rowNumber": 2,
                "primaryIdentifier": "SUB1", "amountCents": 1000,
                "eventTime": "2023-12-01T10:00:00",
                "rawValuesJson": {
                    "订单状态": "已完成", "订单完成时间": "2023-12-01 12:00:00",
                },
            }], [], self.wait_days, task_period="2023-12",
            tolerance_cents=self.tolerance_cents,
        )
        self.assertEqual(result["crossMonth"]["possiblyUnsettledCount"], 1)

    def test_c21_ordinary_account_mismatch_stops_auto_match(self):
        records = _analyze_fixture(_copy_default_rows())["records"]
        fund = next(item for item in records if item["recordType"] == "fund")
        raw = json.loads(fund["rawValuesJson"])
        raw["动账账户"] = "其他账户"
        fund["rawValuesJson"] = raw
        result = calculate_ordinary_settlement_reconciliation(
            records, self.tolerance_cents
        )
        self.assertEqual(result["results"][0]["status"], "not_calculable")

    def test_c22_closed_after_sale_does_not_pass_refund_net_match(self):
        closed = _successful_after_sale()
        closed["rawValuesJson"]["售后状态"] = "售后关闭"
        result = calculate_refund_settlement_reconciliation(
            [_refund_settlement(), _refund_fund(4, "AFTER1", "2023-12-01T10:04:59"), closed],
            self.tolerance_cents, self.auto_group_seconds,
            self.candidate_seconds,
        )
        self.assertEqual(result["results"][0]["status"], "not_calculable")

    def test_c23_mixed_order_months_block_import(self):
        rows = _copy_default_rows()
        november = dict(rows["订单明细"][0])
        november["子订单编号"] = "1002"
        november["主订单编号"] = "MAIN2"
        november["订单提交时间"] = "2023-11-30 23:59:00"
        rows["订单明细"] = (rows["订单明细"][0], november)
        imported = _analyze_fixture(rows)
        self.assertIn("mixed_task_periods", {item["code"] for item in imported["issues"]})

    def _amount_summary(self, code):
        return next(
            item for item in self.amount_checks["checkSummaries"]
            if item["checkCode"] == code
        )


def _copy_default_rows():
    return {
        name: tuple(dict(row) for row in values)
        for name, values in DEFAULT_ROWS.items()
    }


def _analyze_fixture(rows):
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "input.xlsx"
        path.write_bytes(build_workbook_bytes(rows_by_sheet=rows))
        return analyze_workbook_data(path, "2023-12")


def _ordinary_from_fixture(rows, tolerance_cents=1):
    imported = _analyze_fixture(rows)
    return calculate_ordinary_settlement_reconciliation(
        imported["records"], tolerance_cents
    )


def _money_with_difference(difference_cents):
    return "{:.2f}".format((1000 + difference_cents) / 100)


def _time_after(seconds):
    return (
        datetime.fromisoformat("2023-12-01T10:00:00")
        + timedelta(seconds=seconds)
    ).isoformat()


def _refund_settlement():
    return {
        "recordType": "settlement",
        "rowNumber": 3,
        "primaryIdentifier": "SUB1",
        "eventTime": "2023-12-01T10:00:00",
        "amountCents": -1000,
        "rawValuesJson": {"结算单类型": "结算后退款-原路退回"},
    }


def _refund_fund(row, after_sale, event_time):
    return {
        "sourceRecordId": row,
        "recordType": "fund",
        "rowNumber": row,
        "primaryIdentifier": "FUN{}".format(row),
        "secondaryIdentifier": "SUB1",
        "eventTime": event_time,
        "amountCents": -1000,
        "rawValuesJson": {
            "动账场景": "退款-结算后退款-退用户",
            "动账方向": "出账",
            "售后编号": after_sale,
        },
    }


def _successful_after_sale():
    return {
        "sourceRecordId": 9,
        "recordType": "after_sale",
        "rowNumber": 3,
        "primaryIdentifier": "AFTER1",
        "secondaryIdentifier": "SUB1",
        "amountCents": 1000,
        "rawValuesJson": {
            "售后单号": "AFTER1",
            "商品单号": "SUB1",
            "售后状态": "退款成功",
        },
    }


def _other_fund(scene, amount_cents, remark):
    return {
        "sourceRecordId": 1,
        "recordType": "fund",
        "rowNumber": 2,
        "primaryIdentifier": "OTHER1",
        "secondaryIdentifier": None,
        "eventTime": "2023-12-01T10:00:00",
        "amountCents": amount_cents,
        "rawValuesJson": {
            "动账场景": scene,
            "动账方向": "出账" if amount_cents < 0 else "入账",
            "备注": remark,
        },
    }


if __name__ == "__main__":
    unittest.main()
