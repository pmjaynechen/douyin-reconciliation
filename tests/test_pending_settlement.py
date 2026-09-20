import tempfile
import unittest
from pathlib import Path

from recon_app.database import initialize_database
from recon_app.pending_settlement import (
    calculate_pending_settlement,
    inspect_pending_settlement_workbook,
)
from recon_app.services import ReconciliationService, ValidationError


class PendingSettlementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project_root = Path(__file__).resolve().parents[3]
        cls.workbook_path = (
            project_root
            / "对账文件"
            / "抖店测试数据"
            / "抖店M017-M018模拟测试数据.xlsx"
        )

    def test_simulated_workbook_hits_all_m018_priority_branches(self):
        inspection = inspect_pending_settlement_workbook(self.workbook_path)
        self.assertEqual(inspection["status"], "passed")
        self.assertTrue(inspection["trialMode"])
        self.assertEqual(
            [item["dataRowCount"] for item in inspection["sheets"]],
            [8, 10],
        )

        result = calculate_pending_settlement(
            self.workbook_path, "2026-08", 7
        )
        self.assertEqual(result["totalResultCount"], 10)
        self.assertEqual(result["pendingSourceCount"], 8)
        self.assertEqual(result["sourceRowCount"], 18)
        self.assertEqual(result["attentionCount"], 6)
        self.assertEqual(result["waitingCount"], 2)
        self.assertEqual(result["overdueCount"], 2)
        self.assertEqual(result["excludedCount"], 2)
        self.assertEqual(result["pendingAmountCents"], 86900)
        by_scene = {item["sceneCode"]: item for item in result["results"]}
        self.assertEqual(by_scene["PEND-01"]["status"], "waiting")
        self.assertEqual(by_scene["PEND-02"]["status"], "overdue")
        self.assertEqual(by_scene["PEND-03"]["status"], "after_sales")
        self.assertEqual(by_scene["PEND-05A"]["status"], "restricted")
        self.assertEqual(by_scene["PEND-05B"]["status"], "restricted")
        self.assertEqual(by_scene["PEND-06"]["status"], "insufficient")
        self.assertEqual(by_scene["PEND-07A"]["status"], "waiting")
        self.assertEqual(by_scene["PEND-07A"]["recheckAt"], "2026-08-08T12:00:01")
        self.assertEqual(by_scene["PEND-07B"]["status"], "overdue")
        self.assertEqual(by_scene["PEND-04A"]["status"], "canceled_refunded")
        self.assertEqual(by_scene["PEND-04B"]["status"], "canceled_refunded")

    def test_service_persists_filterable_results_and_source_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "test.db"
            initialize_database(database_path)
            service = ReconciliationService(database_path)
            task = service.create_task({
                "entityName": "测试主体",
                "storeName": "M018店铺",
                "period": "2026-08",
            })
            uploaded = service.upload_pending_settlement_workbook(
                task["id"], self.workbook_path.name, self.workbook_path.read_bytes()
            )["pendingSettlement"]
            self.assertEqual(uploaded["latestFile"]["inspectionStatus"], "passed")
            self.assertTrue(uploaded["trialMode"])
            self.assertFalse(uploaded["blockingCompletion"])
            self.assertEqual(uploaded["run"]["attentionCount"], 6)
            self.assertEqual(uploaded["run"]["enforcementMode"], "informational")

            attention = service.get_pending_settlement_results(
                task["id"], "attention", 1, 20
            )
            self.assertEqual(attention["pagination"]["totalRows"], 6)
            self.assertTrue(attention["rows"][0]["source"]["values"])
            self.assertIsNotNone(attention["rows"][0]["auxiliarySource"])
            excluded = service.get_pending_settlement_results(
                task["id"], "excluded", 1, 20
            )
            self.assertEqual(excluded["pagination"]["totalRows"], 2)
            self.assertTrue(all(not row["isAttention"] for row in excluded["rows"]))
            self.assertTrue(all(row["auxiliarySource"] is None for row in excluded["rows"]))

            detail = service.get_task(task["id"])
            self.assertEqual(
                detail["pendingSettlement"]["run"]["id"], uploaded["run"]["id"]
            )
            self.assertEqual(detail["completion"]["systemAttentionCount"], 0)

            with self.assertRaises(ValidationError):
                service.upload_pending_settlement_workbook(
                    task["id"], "重复.xlsx", self.workbook_path.read_bytes()
                )


if __name__ == "__main__":
    unittest.main()
