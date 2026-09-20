import copy
import tempfile
import unittest
from pathlib import Path

from recon_app.xlsx import REQUIRED_SHEETS, WorkbookInspectionError, extract_workbook_rows, inspect_workbook
from xlsx_fixture import build_workbook_bytes


class WorkbookInspectionTests(unittest.TestCase):
    def inspect_bytes(self, content):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "input.xlsx"
            path.write_bytes(content)
            return inspect_workbook(path)

    def test_minimal_five_sheet_workbook_passes_with_volume_warnings(self):
        result = self.inspect_bytes(build_workbook_bytes())
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["foundRequiredSheetCount"], 5)
        self.assertEqual([sheet["dataRowCount"] for sheet in result["sheets"]], [1, 1, 1, 1, 1])
        settlement = next(sheet for sheet in result["sheets"] if sheet["name"] == "结算账单")
        self.assertEqual(settlement["dataStartRow"], 3)
        self.assertEqual(settlement["note"], "平台计算说明")

    def test_missing_sheet_is_reported_as_business_error(self):
        result = self.inspect_bytes(build_workbook_bytes(omit_sheet="资金账单"))
        self.assertEqual(result["status"], "failed")
        self.assertIn("缺少工作表：资金账单", result["errors"])

    def test_missing_required_header_names_sheet_and_field(self):
        result = self.inspect_bytes(
            build_workbook_bytes(omit_header=("订单明细", "订单应付金额"))
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("订单明细缺少必要字段：订单应付金额", result["errors"])

    def test_non_xlsx_is_rejected(self):
        with self.assertRaises(WorkbookInspectionError):
            self.inspect_bytes(b"not a workbook")

    def test_configured_sheet_and_header_aliases_are_canonicalized(self):
        definitions = copy.deepcopy(REQUIRED_SHEETS)
        fund = next(item for item in definitions if item["name"] == "资金账单")
        fund["sheet_aliases"] = ("资金流水",)
        fund["field_aliases"] = {"动帐流水号": ("资金流水号",)}
        content = build_workbook_bytes(
            sheet_name_overrides={"资金账单": "资金流水"},
            header_overrides={("资金账单", "动帐流水号"): "资金流水号"},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "aliased.xlsx"
            path.write_bytes(content)
            inspection = inspect_workbook(path, definitions)
            rows = extract_workbook_rows(path, definitions)
        self.assertEqual(inspection["status"], "passed")
        fund_inspection = next(
            item for item in inspection["sheets"] if item["name"] == "资金账单"
        )
        self.assertEqual(fund_inspection["sourceName"], "资金流水")
        self.assertEqual(rows["资金账单"][0]["values"]["动帐流水号"], "FUN1")

    def test_real_practice_workbook_matches_recorded_baseline(self):
        project_root = Path(__file__).resolve().parents[3]
        workbook_path = project_root / "对账文件" / "抖店练习数据.xlsx"
        result = inspect_workbook(workbook_path)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["warnings"], [])
        self.assertEqual(
            {sheet["name"]: sheet["dataRowCount"] for sheet in result["sheets"]},
            {"订单明细": 2435, "售后表": 212, "结算账单": 381, "资金账单": 655, "成本表": 11},
        )


if __name__ == "__main__":
    unittest.main()
