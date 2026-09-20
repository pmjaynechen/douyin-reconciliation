import json
import tempfile
import unittest
from pathlib import Path

from recon_app.data_import import analyze_workbook_data
from xlsx_fixture import DEFAULT_ROWS, build_workbook_bytes


class DataImportTests(unittest.TestCase):
    def analyze_bytes(self, content, period="2023-12"):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "input.xlsx"
            path.write_bytes(content)
            return analyze_workbook_data(path, period)

    def test_valid_rows_are_normalized_and_saved_with_source_location(self):
        result = self.analyze_bytes(build_workbook_bytes())
        self.assertEqual(result["totalRecordCount"], 5)
        self.assertEqual(result["blockingIssueCount"], 0)
        order = next(item for item in result["records"] if item["recordType"] == "order")
        self.assertEqual(order["sheetName"], "订单明细")
        self.assertEqual(order["rowNumber"], 2)
        self.assertEqual(order["primaryIdentifier"], "1001")
        self.assertEqual(order["amountCents"], 1000)

    def test_duplicate_identifier_invalid_number_and_period_are_blocking(self):
        duplicate = dict(DEFAULT_ROWS["订单明细"][0])
        invalid = dict(duplicate)
        invalid["商品金额"] = "非数字"
        result = self.analyze_bytes(
            build_workbook_bytes(rows_by_sheet={"订单明细": (duplicate, invalid)}),
            period="2024-01",
        )
        codes = {item["code"] for item in result["issues"] if item["severity"] == "blocking"}
        self.assertEqual(result["status"], "failed")
        self.assertIn("duplicate_identifier", codes)
        self.assertIn("invalid_number", codes)
        self.assertIn("task_period_mismatch", codes)
        period_group = next(
            item for item in result["issueGroups"]
            if item["code"] == "task_period_mismatch"
        )
        self.assertEqual(period_group["rawValues"], ["2023-12"])

    def test_real_practice_workbook_has_recorded_quality_baseline_without_pii_copy(self):
        project_root = Path(__file__).resolve().parents[3]
        workbook_path = project_root / "对账文件" / "抖店练习数据.xlsx"
        result = analyze_workbook_data(workbook_path, "2023-12")
        self.assertEqual(result["totalRecordCount"], 3694)
        self.assertEqual(result["blockingIssueCount"], 0)
        self.assertEqual(result["warningIssueCount"], 233)
        order = next(item for item in result["records"] if item["recordType"] == "order")
        saved_values = json.loads(order["rawValuesJson"])
        self.assertNotIn("收件人", saved_values)
        self.assertNotIn("收件人手机号", saved_values)
        self.assertNotIn("收货地址", saved_values)

    def test_order_file_with_multiple_months_is_blocked(self):
        december = dict(DEFAULT_ROWS["订单明细"][0])
        november = dict(december)
        november["子订单编号"] = "1002"
        november["主订单编号"] = "MAIN2"
        november["订单提交时间"] = "2023-11-30 23:59:00"
        result = self.analyze_bytes(build_workbook_bytes(
            rows_by_sheet={"订单明细": (december, november)}
        ))
        codes = {item["code"] for item in result["issues"] if item["severity"] == "blocking"}
        self.assertIn("mixed_task_periods", codes)


if __name__ == "__main__":
    unittest.main()
