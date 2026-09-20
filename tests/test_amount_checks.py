import tempfile
import unittest
from pathlib import Path

from recon_app.amount_checks import calculate_amount_checks
from recon_app.data_import import analyze_workbook_data
from xlsx_fixture import DEFAULT_ROWS, build_workbook_bytes


class AmountCheckTests(unittest.TestCase):
    def analyze(self, content):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "input.xlsx"
            path.write_bytes(content)
            imported = analyze_workbook_data(path, "2023-12")
            return calculate_amount_checks(imported["records"], 1)

    def test_fixture_passes_order_and_four_settlement_checks(self):
        result = self.analyze(build_workbook_bytes())
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["totalCheckCount"], 5)
        self.assertEqual(result["passedCount"], 5)

    def test_one_cent_passes_and_two_cents_fails(self):
        one_cent = dict(DEFAULT_ROWS["订单明细"][0])
        one_cent["订单应付金额"] = "10.01"
        result = self.analyze(build_workbook_bytes(rows_by_sheet={"订单明细": (one_cent,)}))
        order = next(item for item in result["checkSummaries"] if item["checkCode"] == "R01_ORDER_PAYABLE")
        self.assertEqual(order["passedCount"], 1)

        two_cents = dict(one_cent)
        two_cents["订单应付金额"] = "10.02"
        result = self.analyze(build_workbook_bytes(rows_by_sheet={"订单明细": (two_cents,)}))
        order = next(item for item in result["checkSummaries"] if item["checkCode"] == "R01_ORDER_PAYABLE")
        self.assertEqual(order["failedCount"], 1)
        self.assertEqual(result["exceptionPreview"][0]["rowNumber"], 2)

    def test_real_practice_workbook_matches_r01_r02_baseline(self):
        project_root = Path(__file__).resolve().parents[3]
        workbook_path = project_root / "对账文件" / "抖店练习数据.xlsx"
        imported = analyze_workbook_data(workbook_path, "2023-12")
        result = calculate_amount_checks(imported["records"], 1)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["totalCheckCount"], 3959)
        self.assertEqual(result["passedCount"], 3959)
        summaries = {item["checkCode"]: item for item in result["checkSummaries"]}
        self.assertEqual(summaries["R01_ORDER_PAYABLE"]["passedCount"], 2435)
        self.assertEqual(summaries["R01_ORDER_PAYABLE"]["sourceAmountTotalCents"], 238078083)
        self.assertEqual(summaries["R02_ORDER_TOTAL"]["passedCount"], 381)
        self.assertEqual(summaries["R02_ORDER_TOTAL"]["sourceAmountTotalCents"], 60131400)
        self.assertEqual(summaries["R02_INCOME_TOTAL"]["sourceAmountTotalCents"], 58943400)
        self.assertEqual(summaries["R02_EXPENSE_TOTAL"]["sourceAmountTotalCents"], -1217336)
        self.assertEqual(summaries["R02_SETTLEMENT_AMOUNT"]["sourceAmountTotalCents"], 57726064)


if __name__ == "__main__":
    unittest.main()
