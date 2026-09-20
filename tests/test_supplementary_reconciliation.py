import tempfile
import unittest
from pathlib import Path

from recon_app.data_import import analyze_workbook_data
from recon_app.supplementary_reconciliation import (
    calculate_supplementary_reconciliation,
    classify_expected_settlement,
)
from xlsx_fixture import build_workbook_bytes


class SupplementaryReconciliationTests(unittest.TestCase):
    def test_real_workbook_matches_m010_baselines(self):
        project_root = Path(__file__).resolve().parents[3]
        workbook_path = project_root / "对账文件" / "抖店练习数据.xlsx"
        imported = analyze_workbook_data(workbook_path, "2023-12")
        result = calculate_supplementary_reconciliation(
            imported["records"], [], 7, task_period="2023-12", tolerance_cents=1
        )

        cross_month = result["crossMonth"]
        self.assertEqual(cross_month["settlementResultCount"], 375)
        self.assertEqual(cross_month["totalResultCount"], 2549)
        self.assertEqual(cross_month["currentOrderFoundCount"], 261)
        self.assertEqual(cross_month["receivableMatchedCount"], 261)
        self.assertEqual(cross_month["receivableMismatchCount"], 0)
        self.assertEqual(cross_month["possiblyUnsettledCount"], 1)
        self.assertEqual(cross_month["missingHistoricalOrderCount"], 114)
        self.assertTrue(all(
            item["status"] != "missing_historical_order"
            or "不是平台少结" in item["explanation"]
            for item in cross_month["results"]
        ))

        after_sales = result["afterSales"]
        self.assertEqual(after_sales["refundSuccessCount"], 183)
        self.assertEqual(after_sales["closedCount"], 28)
        self.assertEqual(after_sales["exchangeSuccessCount"], 1)
        self.assertEqual(after_sales["multipleAfterSaleOrderCount"], 14)

        costs = result["costs"]
        self.assertEqual(costs["matchedCount"], 2434)
        self.assertEqual(costs["missingSkuCount"], 1)
        self.assertEqual(costs["matchedStaticCostTotalCents"], 136370300)
        self.assertTrue(costs["staticCostWarning"])

        other_funds = result["otherFunds"]
        self.assertEqual(other_funds["totalResultCount"], 265)
        self.assertEqual(other_funds["attentionCount"], 0)
        self.assertEqual(other_funds["categoryCounts"]["monthly_interest"], 21)
        self.assertEqual(other_funds["categoryTotalsCents"]["monthly_interest"], -156228)
        self.assertEqual(other_funds["categoryCounts"]["shipping_insurance"], 231)
        self.assertEqual(other_funds["categoryTotalsCents"]["shipping_insurance"], -116080)
        self.assertEqual(other_funds["categoryCounts"]["consumer_compensation"], 4)
        self.assertEqual(other_funds["categoryTotalsCents"]["consumer_compensation"], -29856)
        self.assertEqual(other_funds["categoryCounts"]["withdrawal"], 9)
        self.assertEqual(other_funds["categoryTotalsCents"]["withdrawal"], -56380830)

    def test_expected_settlement_waiting_and_after_sale_precedence(self):
        waiting = classify_expected_settlement(
            "2023-12-08T09:59:59", completed_at="2023-12-01T10:00:00",
            settlement_wait_days=7,
        )
        self.assertEqual(waiting["status"], "normal_waiting")

        overdue = classify_expected_settlement(
            "2023-12-08T10:00:01", completed_at="2023-12-01T10:00:00",
            settlement_wait_days=7,
        )
        self.assertEqual(overdue["status"], "possibly_unsettled")

        after_sale = classify_expected_settlement(
            "2023-12-09T10:00:00", completed_at="2023-12-01T10:00:00",
            has_open_after_sale=True, settlement_wait_days=7,
        )
        self.assertEqual(after_sale["status"], "waiting_after_sale")
        self.assertIn("不判断平台逾期", after_sale["explanation"])

    def test_unknown_fund_is_waiting_classification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "input.xlsx"
            path.write_bytes(build_workbook_bytes())
            imported = analyze_workbook_data(path, "2023-12")
        for record in imported["records"]:
            if record["recordType"] == "fund":
                record["rawValuesJson"] = {
                    "动账场景": "未配置费用",
                    "动账方向": "出账",
                    "备注": "新费用",
                }
                record["amountCents"] = -500
        result = calculate_supplementary_reconciliation(imported["records"], [], 7)
        other = result["otherFunds"]
        self.assertEqual(other["totalResultCount"], 1)
        self.assertEqual(other["attentionCount"], 1)
        self.assertEqual(other["results"][0]["status"], "waiting_classification")

    def test_unique_historical_order_is_linked(self):
        settlement = {
            "sourceRecordId": 10,
            "recordType": "settlement",
            "rowNumber": 3,
            "primaryIdentifier": "SUB-OLD",
            "amountCents": 1000,
            "rawValuesJson": {
                "结算单类型": "已结算", "下单时间": "2023-11-20",
                "收入合计": "10.00",
            },
        }
        historical = {
            "sourceRecordId": 20,
            "recordType": "order",
            "rowNumber": 8,
            "primaryIdentifier": "SUB-OLD",
            "taskId": "task-history",
            "fileVersionId": "file-history",
            "taskPeriod": "2023-11",
            "amountCents": 1000,
            "rawValuesJson": {
                "平台实际承担优惠金额": 0,
                "达人实际承担优惠金额": 0,
            },
        }
        result = calculate_supplementary_reconciliation([settlement], [historical], 7)
        row = result["crossMonth"]["results"][0]
        self.assertEqual(row["status"], "order_found_history")
        self.assertEqual(row["linkedSourceRecordId"], 20)
        self.assertEqual(row["historicalTaskPeriod"], "2023-11")


if __name__ == "__main__":
    unittest.main()
