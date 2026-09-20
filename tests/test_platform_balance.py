import tempfile
import unittest
from pathlib import Path

from recon_app.database import initialize_database
from recon_app.platform_balance import (
    calculate_platform_balance,
    inspect_platform_balance_workbook,
)
from recon_app.services import ReconciliationService, ValidationError


class PlatformBalanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project_root = Path(__file__).resolve().parents[3]
        cls.workbook_path = (
            project_root
            / "对账文件"
            / "抖店测试数据"
            / "抖店M017-M018模拟测试数据.xlsx"
        )

    def test_simulated_workbook_hits_all_m017_scenarios(self):
        inspection = inspect_platform_balance_workbook(self.workbook_path)
        self.assertEqual(inspection["status"], "passed")
        self.assertTrue(inspection["trialMode"])
        self.assertEqual(
            [item["dataRowCount"] for item in inspection["sheets"]],
            [16, 8, 7],
        )

        result = calculate_platform_balance(self.workbook_path, "2026-07", 1)
        self.assertEqual(result["totalResultCount"], 16)
        self.assertEqual(result["matchedCount"], 7)
        self.assertEqual(result["attentionCount"], 9)
        self.assertEqual(result["dateGapCount"], 1)
        self.assertEqual(result["statusCounts"]["detail_incomplete"], 7)
        self.assertEqual(result["statusCounts"]["account_period_mismatch"], 2)
        gap = next(
            item
            for item in result["results"]
            if item["metadata"].get("checkType") == "date_gap"
        )
        self.assertEqual(gap["batchKey"], "BAL_GAP")
        self.assertEqual(gap["periodKey"], "2026-07-02")
        self.assertIn("月汇总一致也不能证明", gap["explanation"])

    def test_service_saves_trial_results_without_blocking_period_completion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "test.db"
            initialize_database(database_path)
            service = ReconciliationService(database_path)
            task = service.create_task({
                "entityName": "测试主体",
                "storeName": "M017店铺",
                "period": "2026-07",
            })
            uploaded = service.upload_platform_balance_workbook(
                task["id"], self.workbook_path.name, self.workbook_path.read_bytes()
            )["platformBalance"]
            self.assertEqual(uploaded["latestFile"]["inspectionStatus"], "passed")
            self.assertTrue(uploaded["trialMode"])
            self.assertFalse(uploaded["blockingCompletion"])
            self.assertEqual(uploaded["run"]["attentionCount"], 9)
            self.assertEqual(uploaded["run"]["enforcementMode"], "informational")

            page = service.get_platform_balance_results(
                task["id"], "attention", 1, 20
            )
            self.assertEqual(page["pagination"]["totalRows"], 9)
            self.assertTrue(page["rows"][0]["source"]["sheetName"])
            self.assertIn(page["rows"][0]["status"], {
                "detail_incomplete", "account_period_mismatch"
            })

            detail = service.get_task(task["id"])
            self.assertEqual(detail["platformBalance"]["run"]["id"], uploaded["run"]["id"])
            self.assertEqual(detail["completion"]["systemAttentionCount"], 0)

            with self.assertRaises(ValidationError):
                service.upload_platform_balance_workbook(
                    task["id"], "重复.xlsx", self.workbook_path.read_bytes()
                )


if __name__ == "__main__":
    unittest.main()
