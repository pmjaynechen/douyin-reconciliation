import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from recon_app.database import connect, initialize_database
from recon_app.services import ReconciliationService, ValidationError
from xlsx_fixture import DEFAULT_ROWS, build_workbook_bytes


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name) / "var"
        self.database_path = self.data_dir / "reconciliation.db"
        self.upload_dir = self.data_dir / "uploads"
        initialize_database(self.database_path)
        self.service = ReconciliationService(self.database_path, self.upload_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_import_reconcile_complete_export_and_restart(self):
        task = self.service.create_task(
            {"entityName": "全流程主体", "storeName": "全流程店铺", "period": "2023-12"}
        )
        uploaded = self.service.upload_workbook(
            task["id"], "完整流程.xlsx", build_workbook_bytes()
        )
        file_id = uploaded["file"]["id"]
        self.assertEqual(uploaded["task"]["status"], "ready")
        self.assertEqual(uploaded["file"]["amountCheckStatus"], "passed")
        self.assertEqual(uploaded["file"]["reconciliationStatus"], "passed")
        self.assertEqual(uploaded["file"]["reconciliation"]["matchedCount"], 1)
        self.assertEqual(uploaded["file"]["refundReconciliationStatus"], "passed")
        self.assertEqual(uploaded["file"]["supplementaryReconciliationStatus"], "passed")

        completion = self.service.get_completion_summary(task["id"])["completion"]
        self.assertTrue(completion["canComplete"])
        completed = self.service.complete_task(
            task["id"], {"confirmed": True, "note": "全流程测试确认完成"}
        )
        self.assertEqual(completed["task"]["status"], "completed")

        exported = self.service.export_results(
            task["id"], file_id, "ordinary_settlement", "all"
        )
        self.assertEqual(exported["rowCount"], 1)
        with zipfile.ZipFile(BytesIO(exported["content"])) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn("xl/worksheets/sheet2.xml", archive.namelist())

        restarted = ReconciliationService(self.database_path, self.upload_dir)
        restored_task = restarted.get_task(task["id"])
        self.assertEqual(restored_task["task"]["status"], "completed")
        self.assertEqual(restored_task["files"][0]["id"], file_id)
        self.assertEqual(restored_task["files"][0]["reconciliation"]["matchedCount"], 1)
        self.assertTrue((self.upload_dir / task["id"] / "{}.xlsx".format(file_id)).is_file())

        changed_rows = _copy_default_rows()
        changed_rows["成本表"][0]["成本价"] = "6.51"
        with self.assertRaises(ValidationError):
            restarted.upload_workbook(
                task["id"], "完成后不允许重传.xlsx", build_workbook_bytes(rows_by_sheet=changed_rows)
            )

        with connect(self.database_path) as connection:
            actions = {
                row["action"] for row in connection.execute(
                    "SELECT action FROM operation_logs WHERE task_id = ?", (task["id"],)
                ).fetchall()
            }
        self.assertTrue(
            {"task_created", "workbook_uploaded", "period_completed", "results_exported"}
            .issubset(actions)
        )

    def test_failed_matching_stays_attention_and_cannot_complete(self):
        rows = _copy_default_rows()
        second_fund = dict(rows["资金账单"][0])
        second_fund["动帐流水号"] = "FUN2"
        rows["资金账单"] = (rows["资金账单"][0], second_fund)

        task = self.service.create_task(
            {"entityName": "异常流程主体", "storeName": "异常流程店铺", "period": "2023-12"}
        )
        uploaded = self.service.upload_workbook(
            task["id"], "多候选.xlsx", build_workbook_bytes(rows_by_sheet=rows)
        )
        file_id = uploaded["file"]["id"]
        ordinary = uploaded["file"]["reconciliation"]
        self.assertEqual(uploaded["task"]["status"], "needs_attention")
        self.assertEqual(ordinary["matchedCount"], 0)
        self.assertEqual(ordinary["attentionCount"], 1)
        self.assertEqual(ordinary["statusCounts"]["multiple_candidates"], 1)

        page = self.service.get_reconciliation_results(
            task["id"], file_id, "needs_attention", 1, 20
        )
        self.assertEqual(page["pagination"]["totalRows"], 1)
        self.assertEqual(page["rows"][0]["status"], "multiple_candidates")
        self.assertNotEqual(page["rows"][0]["status"], "matched")

        completion = self.service.get_completion_summary(task["id"])["completion"]
        self.assertFalse(completion["canComplete"])
        self.assertEqual(completion["unresolvedCount"], 1)
        with self.assertRaises(ValidationError):
            self.service.complete_task(task["id"], {"confirmed": True})

        restarted = ReconciliationService(self.database_path, self.upload_dir)
        after_restart = restarted.get_reconciliation_results(
            task["id"], file_id, "needs_attention", 1, 20
        )
        self.assertEqual(after_restart["rows"][0]["status"], "multiple_candidates")

    def test_order_receivable_mismatch_blocks_completion_even_when_internal_totals_match(self):
        rows = _copy_default_rows()
        settlement = rows["结算账单"][0]
        for field in ("结算金额", "订单总价", "商品总价", "用户实付", "收入合计"):
            settlement[field] = "1.00"
        settlement["运费"] = "0"
        rows["资金账单"][0]["动账金额"] = "1.00"
        task = self.service.create_task(
            {"entityName": "应收反例主体", "storeName": "应收反例店", "period": "2023-12"}
        )
        uploaded = self.service.upload_workbook(
            task["id"], "应收差异.xlsx", build_workbook_bytes(rows_by_sheet=rows)
        )
        self.assertEqual(uploaded["file"]["amountCheckStatus"], "passed")
        self.assertEqual(uploaded["file"]["reconciliationStatus"], "passed")
        cross = uploaded["file"]["supplementaryReconciliation"]["crossMonth"]
        self.assertEqual(cross["receivableMismatchCount"], 1)
        self.assertFalse(self.service.get_completion_summary(task["id"])["completion"]["canComplete"])

    def test_overdue_completed_order_without_settlement_blocks_completion(self):
        rows = _copy_default_rows()
        second_order = dict(rows["订单明细"][0])
        second_order.update({
            "子订单编号": "1002", "主订单编号": "MAIN2",
            "订单完成时间": "2023-12-01 12:00:00",
            "订单应付金额": "20.00", "商品金额": "19.90",
        })
        rows["订单明细"] = (rows["订单明细"][0], second_order)
        task = self.service.create_task(
            {"entityName": "未结算反例主体", "storeName": "未结算反例店", "period": "2023-12"}
        )
        uploaded = self.service.upload_workbook(
            task["id"], "未结算订单.xlsx", build_workbook_bytes(rows_by_sheet=rows)
        )
        cross = uploaded["file"]["supplementaryReconciliation"]["crossMonth"]
        self.assertEqual(cross["possiblyUnsettledCount"], 1)
        self.assertEqual(uploaded["task"]["status"], "needs_attention")
        self.assertFalse(self.service.get_completion_summary(task["id"])["completion"]["canComplete"])


def _copy_default_rows():
    return {
        name: tuple(dict(row) for row in values)
        for name, values in DEFAULT_ROWS.items()
    }


if __name__ == "__main__":
    unittest.main()
