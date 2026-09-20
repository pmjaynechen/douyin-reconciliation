import tempfile
import unittest
from pathlib import Path

from recon_app.database import connect, initialize_database
from recon_app.services import DuplicateTaskError, ReconciliationService, ValidationError, validate_period
from recon_app.services import DuplicateFileError
from xlsx_fixture import (
    DEFAULT_ROWS,
    build_operating_evidence_workbook_bytes,
    build_workbook_bytes,
)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        self.sample_path = Path(self.temp_dir.name) / "sample.xlsx"
        self.sample_path.write_bytes(build_workbook_bytes())
        initialize_database(self.database_path)
        self.service = ReconciliationService(
            self.database_path, sample_workbook_path=self.sample_path
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_database_is_initialized_with_default_rule(self):
        health = self.service.health()
        rule = self.service.current_rule()
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["schemaVersion"], 19)
        self.assertEqual(rule["versionLabel"], "V1.1")
        self.assertEqual(rule["toleranceCents"], 1)
        self.assertEqual(rule["refundAutoGroupSeconds"], 300)
        self.assertEqual(rule["refundCandidateSeconds"], 86400)
        self.assertEqual(rule["settlementWaitDays"], 7)

    def test_master_data_drives_task_selection_and_disabled_store_is_blocked(self):
        self.assertEqual(self.service.master_data_options()["entities"], [])
        created_entities = self.service.create_business_entity({"name": "测试商贸"})
        entity = created_entities["entities"][0]
        created_stores = self.service.create_platform_store(
            {"entityId": entity["id"], "name": "抖店测试店"}
        )
        store = created_stores["entities"][0]["stores"][0]
        task = self.service.create_task(
            {"storeId": store["id"], "period": "2023-12"}
        )
        self.assertEqual(task["entityName"], "测试商贸")
        self.assertEqual(task["storeName"], "抖店测试店")
        with connect(self.database_path) as connection:
            stored = connection.execute(
                "SELECT entity_id, store_id FROM tasks WHERE id = ?", (task["id"],)
            ).fetchone()
        self.assertEqual(stored["entity_id"], entity["id"])
        self.assertEqual(stored["store_id"], store["id"])

        self.service.update_platform_store_status(store["id"], {"status": "inactive"})
        with self.assertRaises(ValidationError):
            self.service.create_task({"storeId": store["id"], "period": "2024-01"})

    def test_unknown_platform_values_are_mapped_for_future_imports_with_version_snapshot(self):
        rows = {
            sheet_name: tuple(dict(row) for row in sheet_rows)
            for sheet_name, sheet_rows in DEFAULT_ROWS.items()
        }
        rows["售后表"][0]["售后状态"] = "平台退款完成"
        rows["资金账单"][0]["动账场景"] = "货款入账新版"
        workbook = build_workbook_bytes(rows_by_sheet=rows)
        first_task = self.service.create_task(
            {"entityName": "测试主体", "storeName": "待映射店", "period": "2023-12"}
        )
        first_upload = self.service.upload_workbook(first_task["id"], "新平台值.xlsx", workbook)
        pending = self.service.configuration_center()["unmappedValues"]
        self.assertEqual(
            {(item["mappingType"], item["sourceValue"]) for item in pending},
            {
                ("after_sale_status", "平台退款完成"),
                ("fund_scene", "货款入账新版"),
            },
        )
        self.assertEqual(first_upload["file"]["dataImport"]["mappingSummary"]["pendingValueCount"], 2)

        self.service.create_platform_value_mapping({
            "mappingType": "after_sale_status",
            "sourceValue": "平台退款完成",
            "standardCode": "refund_success",
            "effectiveFrom": "2023-12-01",
            "notes": "测试样例确认该值代表退款成功",
        })
        mapped_configuration = self.service.create_platform_value_mapping({
            "mappingType": "fund_scene",
            "sourceValue": "货款入账新版",
            "standardCode": "ordinary_settlement_receipt",
            "effectiveFrom": "2023-12-01",
            "notes": "测试样例确认该值代表货款结算入账",
        })
        self.assertEqual(mapped_configuration["unmappedValues"], [])

        second_task = self.service.create_task(
            {"entityName": "测试主体", "storeName": "映射生效店", "period": "2023-12"}
        )
        second_upload = self.service.upload_workbook(second_task["id"], "映射后.xlsx", workbook)
        mapping_summary = second_upload["file"]["dataImport"]["mappingSummary"]
        self.assertEqual(mapping_summary["pendingValueCount"], 0)
        self.assertGreaterEqual(mapping_summary["appliedMappingCount"], 2)
        detail = self.service.get_task(second_task["id"])
        latest = detail["files"][0]
        self.assertEqual(latest["reconciliation"]["matchedCount"], 1)
        self.assertEqual(
            latest["supplementaryReconciliation"]["afterSales"]["refundSuccessCount"], 1
        )
        with connect(self.database_path) as connection:
            mapped_source = connection.execute(
                """
                SELECT raw_values_json, mapped_values_json, mapping_snapshot_json
                FROM source_records
                WHERE task_id = ? AND record_type = 'fund'
                """,
                (second_task["id"],),
            ).fetchone()
        self.assertIn("货款入账新版", mapped_source["raw_values_json"])
        self.assertIn("货款结算入账", mapped_source["mapped_values_json"])
        self.assertIn("mappingId", mapped_source["mapping_snapshot_json"])

    def test_rule_draft_requires_fixed_cases_and_only_new_tasks_use_activated_version(self):
        old_task = self.service.create_task(
            {"entityName": "测试主体", "storeName": "旧规则店", "period": "2023-12"}
        )
        self.assertEqual(old_task["ruleVersionLabel"], "V1.1")

        overview = self.service.configuration_center()
        self.assertIsNone(overview["draftRule"])
        self.assertEqual(overview["releaseBoundary"]["ruleMaintenance"], "available")
        draft = self.service.create_rule_draft()
        self.assertEqual(draft["versionLabel"], "V1.2")
        with self.assertRaises(ValidationError):
            self.service.activate_rule_draft(draft["id"], {"confirmed": True})
        with self.assertRaises(ValidationError):
            self.service.update_rule_draft(
                draft["id"],
                {
                    "toleranceCents": 2,
                    "refundAutoGroupSeconds": 600,
                    "refundCandidateSeconds": 300,
                    "settlementWaitDays": 10,
                    "notes": "无效时间窗口",
                },
            )

        updated = self.service.update_rule_draft(
            draft["id"],
            {
                "toleranceCents": 2,
                "refundAutoGroupSeconds": 600,
                "refundCandidateSeconds": 172800,
                "settlementWaitDays": 10,
                "notes": "扩大退款候选范围，并延长结算等待期",
            },
        )
        self.assertIsNone(updated["lastTestStatus"])
        tested = self.service.test_rule_draft(draft["id"])
        self.assertEqual(tested["fixedCases"]["status"], "passed")
        self.assertEqual(tested["fixedCases"]["passedCount"], 23)
        activated = self.service.activate_rule_draft(
            draft["id"], {"confirmed": True}
        )
        self.assertEqual(activated["currentRule"]["versionLabel"], "V1.2")
        self.assertIsNone(activated["draftRule"])

        old_detail = self.service.get_task(old_task["id"])
        self.assertEqual(old_detail["task"]["ruleVersionLabel"], "V1.1")
        new_task = self.service.create_task(
            {"entityName": "测试主体", "storeName": "新规则店", "period": "2023-12"}
        )
        self.assertEqual(new_task["ruleVersionLabel"], "V1.2")

    def test_template_draft_must_pass_sample_before_activation_and_new_imports_keep_version(self):
        first_task = self.service.create_task(
            {"entityName": "测试主体", "storeName": "旧模板店", "period": "2023-12"}
        )
        first_upload = self.service.upload_workbook(
            first_task["id"], "旧格式.xlsx", build_workbook_bytes()
        )
        self.assertEqual(first_upload["file"]["templateVersionLabel"], "V1.0")

        overview = self.service.configuration_center()
        self.assertEqual(overview["currentTemplate"]["versionLabel"], "V1.0")
        self.assertEqual(len(overview["rules"]), 13)
        self.assertEqual(overview["releaseBoundary"]["templateMaintenance"], "available")
        draft = self.service.create_bill_template_draft()
        self.assertEqual(draft["versionLabel"], "V1.1")
        with self.assertRaises(ValidationError):
            self.service.activate_bill_template(draft["id"], {"confirmed": True})

        fund_sheet = next(
            item for item in draft["sheets"] if item["displayName"] == "资金账单"
        )
        fund_id_field = next(
            item for item in fund_sheet["fields"] if item["displayName"] == "动帐流水号"
        )
        updated = self.service.update_bill_template_draft(
            draft["id"],
            {
                "name": "抖店五表新表头",
                "notes": "验证Sheet和字段别名",
                "sheets": [{
                    "id": fund_sheet["id"],
                    "sourceSheetName": fund_sheet["sourceSheetName"],
                    "sourceSheetAliases": ["资金流水"],
                    "headerRow": 1,
                    "dataStartRow": 2,
                    "fields": [{
                        "id": fund_id_field["id"],
                        "sourceHeader": fund_id_field["sourceHeader"],
                        "sourceAliases": ["动账流水号", "资金流水号"],
                    }],
                }],
            },
        )
        self.assertIsNone(updated["lastTestStatus"])
        aliased_workbook = build_workbook_bytes(
            sheet_name_overrides={"资金账单": "资金流水"},
            header_overrides={("资金账单", "动帐流水号"): "资金流水号"},
        )
        tested = self.service.test_bill_template(
            draft["id"], "平台新格式.xlsx", aliased_workbook
        )
        self.assertEqual(tested["inspection"]["status"], "passed")
        activated = self.service.activate_bill_template(
            draft["id"], {"confirmed": True}
        )
        self.assertEqual(activated["currentTemplate"]["versionLabel"], "V1.1")

        second_task = self.service.create_task(
            {"entityName": "测试主体", "storeName": "新模板店", "period": "2023-12"}
        )
        second_upload = self.service.upload_workbook(
            second_task["id"], "新格式.xlsx", aliased_workbook
        )
        self.assertEqual(second_upload["file"]["inspectionStatus"], "passed")
        self.assertEqual(second_upload["file"]["templateVersionLabel"], "V1.1")
        first_detail = self.service.get_task(first_task["id"])
        self.assertEqual(first_detail["files"][0]["templateVersionLabel"], "V1.0")

    def test_create_and_list_task(self):
        self.assertEqual(self.service.list_tasks(), [])
        task = self.service.create_task(
            {"entityName": " 示例商贸公司 ", "storeName": " 抖店A店 ", "period": "2023-12"}
        )
        tasks = self.service.list_tasks()
        self.assertEqual(task["status"], "draft")
        self.assertEqual(task["entityName"], "示例商贸公司")
        self.assertEqual(task["ruleVersionLabel"], "V1.1")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["id"], task["id"])
        self.assertFalse(tasks[0]["isSample"])

        with connect(self.database_path) as connection:
            log = connection.execute(
                "SELECT action, task_id FROM operation_logs WHERE task_id = ?", (task["id"],)
            ).fetchone()
        self.assertEqual(log["action"], "task_created")

    def test_operating_report_readiness_never_invents_profit(self):
        task = self.service.create_task(
            {"entityName": "测试主体", "storeName": "经营报表店", "period": "2023-12"}
        )
        empty = self.service.get_operating_report_readiness(task["id"])
        self.assertEqual(empty["status"], "no_import")
        self.assertIsNone(empty["summary"]["settlementNetCents"])
        self.assertFalse(empty["completeness"]["canIssueProfit"])

        self.service.upload_workbook(
            task["id"], "经营报表准备度.xlsx", build_workbook_bytes()
        )
        report = self.service.get_operating_report_readiness(task["id"])
        self.assertEqual(report["status"], "data_pending")
        self.assertEqual(report["summary"]["settlementIncomeCents"], 1000)
        self.assertEqual(report["summary"]["settlementExpenseCents"], 0)
        self.assertEqual(report["summary"]["settlementNetCents"], 1000)
        self.assertEqual(report["summary"]["successfulRefundCents"], 1000)
        self.assertEqual(report["summary"]["staticCostCents"], 650)
        self.assertTrue(report["summary"]["settlementFormulaConsistent"])
        self.assertTrue(report["completeness"]["canIssueReconciliationReport"])
        self.assertFalse(report["completeness"]["canIssueProfit"])
        profit_line = next(
            item for item in report["statement"]["lines"]
            if item["code"] == "operating_profit"
        )
        self.assertIsNone(profit_line["amountCents"])
        self.assertEqual(profit_line["status"], "blocked")
        self.assertEqual(
            [item["taskId"] for item in report["completeness"]["blockingItems"]],
            ["M017-B", "M018-B", "M019-B", "M020", "M021", "M022-B"],
        )

    def test_operating_evidence_is_versioned_but_never_treated_as_profit_ready(self):
        task = self.service.create_task(
            {"entityName": "测试主体", "storeName": "经营资料店", "period": "2023-12"}
        )
        initial = self.service.get_operating_evidence(task["id"])["operatingEvidence"]
        self.assertEqual(initial["receivedTypeCount"], 0)
        first = self.service.upload_operating_evidence_file(
            task["id"], "erp_cost", "ERP成本.csv", b"order_id,cost\n1,6.50\n"
        )["operatingEvidence"]
        erp = next(item for item in first["categories"] if item["code"] == "erp_cost")
        self.assertEqual(erp["status"], "received_pending_mapping")
        self.assertEqual(erp["versionCount"], 1)
        self.assertFalse(first["mappingComplete"])
        self.assertFalse(first["canCalculateProfit"])

        with self.assertRaises(ValidationError):
            self.service.upload_operating_evidence_file(
                task["id"], "erp_cost", "ERP成本.csv", b"order_id,cost\n1,6.50\n"
            )
        with self.assertRaises(ValidationError):
            self.service.upload_operating_evidence_file(
                task["id"], "erp_cost", "ERP成本新版.csv", b"order_id,cost\n1,7.00\n"
            )
        second = self.service.upload_operating_evidence_file(
            task["id"], "erp_cost", "ERP成本新版.csv",
            b"order_id,cost\n1,7.00\n", "成本版本更新"
        )["operatingEvidence"]
        erp = next(item for item in second["categories"] if item["code"] == "erp_cost")
        self.assertEqual(erp["versionCount"], 2)
        self.assertEqual(erp["latestFile"]["originalName"], "ERP成本新版.csv")

        readiness = self.service.get_operating_report_readiness(task["id"])
        self.assertEqual(readiness["status"], "no_import")
        self.assertFalse(readiness["completeness"]["canIssueProfit"])
        blocker = next(
            item for item in readiness["completeness"]["blockingItems"]
            if item["taskId"] == "M020"
        )
        self.assertEqual(blocker["status"], "received_pending_mapping")

    def test_operating_evidence_rejects_unknown_type_and_unsupported_file(self):
        task = self.service.create_task(
            {"entityName": "测试主体", "storeName": "资料校验店", "period": "2023-12"}
        )
        with self.assertRaises(ValidationError):
            self.service.upload_operating_evidence_file(
                task["id"], "unknown", "资料.csv", b"a,b\n1,2\n"
            )
        with self.assertRaises(ValidationError):
            self.service.upload_operating_evidence_file(
                task["id"], "erp_cost", "资料.pdf", b"not-a-table"
            )

    def test_simulated_operating_evidence_generates_traceable_trial_profit_only_for_sample(self):
        sample = self.service.load_sample()
        task = sample["task"]
        workbook = build_operating_evidence_workbook_bytes(task["id"])
        for evidence_type in ("erp_cost", "fulfillment_expense", "operating_expense"):
            uploaded = self.service.upload_operating_evidence_file(
                task["id"], evidence_type, "经营模拟资料.xlsx", workbook
            )["operatingEvidence"]
        self.assertEqual(uploaded["processedTypeCount"], 3)
        self.assertTrue(uploaded["mappingComplete"])
        self.assertTrue(uploaded["canCalculateProfit"])

        report = self.service.get_operating_report_readiness(task["id"])
        self.assertEqual(report["status"], "trial_ready")
        self.assertTrue(report["completeness"]["canIssueTrialProfit"])
        self.assertFalse(report["completeness"]["canIssueProfit"])
        self.assertEqual(report["profitTrial"]["amountCents"], 750)
        self.assertEqual(report["profitTrial"]["dataMode"], "simulated_trial")

        detail = self.service.get_operating_evidence_results(
            task["id"], "fulfillment_expense"
        )
        self.assertEqual(detail["pagination"]["total"], 1)
        self.assertEqual(detail["rows"][0]["primaryIdentifier"], "1001")
        self.assertEqual(detail["rows"][0]["amountCents"], 150)

        real_task = self.service.create_task(
            {"entityName": "测试主体", "storeName": "真实任务店", "period": "2023-12"}
        )
        self.service.upload_workbook(
            real_task["id"], "真实任务账单.xlsx", build_workbook_bytes()
        )
        real_workbook = build_operating_evidence_workbook_bytes(
            real_task["id"], store_name="真实任务店"
        )
        with self.assertRaisesRegex(ValidationError, "只能用于样例任务"):
            self.service.upload_operating_evidence_file(
                real_task["id"], "erp_cost", "模拟资料.xlsx", real_workbook
            )

    def test_duplicate_task_returns_existing_task(self):
        payload = {"entityName": "示例商贸公司", "storeName": "抖店A店", "period": "2023-12"}
        first = self.service.create_task(payload)
        with self.assertRaises(DuplicateTaskError) as context:
            self.service.create_task(payload)
        self.assertEqual(context.exception.task["id"], first["id"])

    def test_invalid_period_is_rejected(self):
        for value in (None, "2023-13", "2023/12", "23-12"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate_period(value)

    def test_upload_workbook_updates_task_and_preserves_version(self):
        task = self.service.create_task(
            {"entityName": "示例商贸公司", "storeName": "抖店A店", "period": "2023-12"}
        )
        result = self.service.upload_workbook(
            task["id"], "抖店练习数据.xlsx", build_workbook_bytes()
        )
        self.assertEqual(result["task"]["status"], "ready")
        self.assertEqual(result["file"]["inspectionStatus"], "passed")
        self.assertEqual(result["file"]["inspection"]["foundRequiredSheetCount"], 5)
        self.assertEqual(result["file"]["dataImportStatus"], "warning")
        self.assertEqual(result["file"]["dataImport"]["totalRecordCount"], 5)
        self.assertEqual(result["file"]["dataImport"]["blockingIssueCount"], 0)
        order_summary = next(
            item
            for item in result["file"]["dataImport"]["sheetSummaries"]
            if item["name"] == "订单明细"
        )
        self.assertEqual(order_summary["columnCount"], 16)
        self.assertEqual(order_summary["displayColumnCount"], 15)
        self.assertEqual(order_summary["amountSummary"]["valueCents"], 1000)
        self.assertEqual(result["file"]["amountCheckStatus"], "passed")
        self.assertEqual(result["file"]["amountChecks"]["totalCheckCount"], 5)
        self.assertEqual(result["file"]["amountChecks"]["passedCount"], 5)
        self.assertEqual(result["file"]["reconciliationStatus"], "passed")
        self.assertEqual(result["file"]["reconciliation"]["totalResultCount"], 1)
        self.assertEqual(result["file"]["reconciliation"]["matchedCount"], 1)
        self.assertEqual(result["file"]["refundReconciliationStatus"], "passed")
        self.assertEqual(result["file"]["refundReconciliation"]["totalResultCount"], 0)
        self.assertEqual(result["file"]["supplementaryReconciliationStatus"], "passed")
        self.assertEqual(
            result["file"]["supplementaryReconciliation"]["crossMonth"]["totalResultCount"], 1
        )
        stored_path = self.service.upload_dir / task["id"] / "{}.xlsx".format(result["file"]["id"])
        self.assertTrue(stored_path.exists())

        detail = self.service.get_task(task["id"])
        self.assertEqual(len(detail["files"]), 1)
        self.assertEqual(detail["files"][0]["id"], result["file"]["id"])

        page = self.service.get_import_records(
            task["id"], result["file"]["id"], "订单明细", 1, 20
        )
        self.assertEqual(page["pagination"]["totalRows"], 1)
        self.assertEqual(page["rows"][0]["values"]["subOrderId"], "1001")
        self.assertEqual(page["rows"][0]["values"]["payableAmount"], 1000)
        self.assertNotIn("收件人", [item["label"] for item in page["columns"]])

        reconciliation = self.service.get_reconciliation_results(
            task["id"], result["file"]["id"], "all", 1, 20
        )
        self.assertEqual(reconciliation["pagination"]["totalRows"], 1)
        self.assertEqual(reconciliation["rows"][0]["status"], "matched")
        self.assertEqual(reconciliation["rows"][0]["subOrderId"], "1001")
        result_detail = self.service.get_reconciliation_result(
            task["id"], result["file"]["id"], reconciliation["rows"][0]["id"]
        )["result"]
        self.assertEqual(result_detail["settlementSource"]["rowNumber"], 3)
        self.assertEqual(result_detail["fundSource"]["rowNumber"], 2)
        self.assertEqual(result_detail["fundSource"]["values"]["动账场景"], "货款结算入账")

        with connect(self.database_path) as connection:
            saved_records = connection.execute(
                "SELECT COUNT(*) AS count FROM source_records WHERE task_id = ?",
                (task["id"],),
            ).fetchone()["count"]
            saved_issues = connection.execute(
                "SELECT COUNT(*) AS count FROM data_issues WHERE task_id = ?",
                (task["id"],),
            ).fetchone()["count"]
            saved_checks = connection.execute(
                "SELECT COUNT(*) AS count FROM amount_check_results WHERE task_id = ?",
                (task["id"],),
            ).fetchone()["count"]
            saved_reconciliation_results = connection.execute(
                "SELECT COUNT(*) AS count FROM reconciliation_results WHERE task_id = ?",
                (task["id"],),
            ).fetchone()["count"]
            saved_supplementary_results = connection.execute(
                "SELECT COUNT(*) AS count FROM supplementary_reconciliation_results WHERE task_id = ?",
                (task["id"],),
            ).fetchone()["count"]
        self.assertEqual(saved_records, 5)
        self.assertEqual(saved_issues, 1)
        self.assertEqual(saved_checks, 5)
        self.assertEqual(saved_reconciliation_results, 1)
        self.assertEqual(saved_supplementary_results, 3)

        with self.assertRaises(DuplicateFileError):
            self.service.upload_workbook(
                task["id"], "相同内容.xlsx", build_workbook_bytes()
            )

        with self.assertRaises(ValidationError) as context:
            self.service.upload_workbook(
                task["id"], "缺少一张表.xlsx", build_workbook_bytes(omit_sheet="资金账单")
            )
        self.assertIn("重传说明", str(context.exception))

        replacement = self.service.upload_workbook(
            task["id"],
            "缺少一张表.xlsx",
            build_workbook_bytes(omit_sheet="资金账单"),
            "验证旧文件保留",
        )
        self.assertEqual(replacement["task"]["status"], "needs_attention")
        self.assertEqual(replacement["file"]["replacementReason"], "验证旧文件保留")
        self.assertEqual(len(self.service.get_task(task["id"])["files"]), 2)

    def test_real_refund_results_are_saved_and_source_rows_can_be_opened(self):
        task = self.service.create_task(
            {"entityName": "示例商贸公司", "storeName": "退款归组验证", "period": "2023-12"}
        )
        project_root = Path(__file__).resolve().parents[3]
        workbook_path = project_root / "对账文件" / "抖店练习数据.xlsx"
        uploaded = self.service.upload_workbook(
            task["id"], workbook_path.name, workbook_path.read_bytes()
        )
        refund = uploaded["file"]["refundReconciliation"]
        self.assertEqual(uploaded["file"]["refundReconciliationStatus"], "passed")
        self.assertEqual(refund["totalResultCount"], 6)
        self.assertEqual(refund["matchedCount"], 6)
        self.assertEqual(refund["settlementAmountTotalCents"], -1158760)
        self.assertEqual(refund["matchedFundAmountTotalCents"], -1158760)
        self.assertEqual(refund["componentMatchedCount"], 5)
        self.assertEqual(refund["componentLimitedCount"], 1)
        self.assertEqual(refund["componentMismatchCount"], 0)

        page = self.service.get_refund_reconciliation_results(
            task["id"], uploaded["file"]["id"], "all", 1, 20
        )
        self.assertEqual(page["pagination"]["totalRows"], 6)
        self.assertEqual(page["rows"][0]["status"], "matched")
        self.assertGreaterEqual(page["rows"][0]["selectedRecordCount"], 1)
        self.assertIn(page["rows"][0]["componentStatus"], {"matched", "limited"})

        detail = self.service.get_refund_reconciliation_result(
            task["id"], uploaded["file"]["id"], page["rows"][0]["id"]
        )["result"]
        self.assertEqual(detail["settlementSource"]["sheetName"], "结算账单")
        self.assertGreaterEqual(len(detail["fundSources"]), 1)
        self.assertTrue(all(item["sheetName"] == "资金账单" for item in detail["fundSources"]))
        self.assertTrue(detail["componentCheck"]["isTrial"])
        self.assertIn("外部课程资料", detail["componentCheck"]["ruleSource"])

        with connect(self.database_path) as connection:
            before_ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM refund_reconciliation_results ORDER BY id"
                ).fetchall()
            ]
            connection.execute(
                "UPDATE refund_reconciliation_results SET component_status = NULL, component_json = NULL"
            )
        self.assertEqual(self.service.backfill_pending_refund_component_checks(), 1)
        with connect(self.database_path) as connection:
            after = connection.execute(
                "SELECT id, component_status, component_json FROM refund_reconciliation_results ORDER BY id"
            ).fetchall()
        self.assertEqual([row["id"] for row in after], before_ids)
        self.assertTrue(all(row["component_status"] for row in after))
        self.assertTrue(all(row["component_json"] for row in after))

        supplementary = uploaded["file"]["supplementaryReconciliation"]
        self.assertEqual(supplementary["crossMonth"]["missingHistoricalOrderCount"], 114)
        self.assertEqual(supplementary["afterSales"]["multipleAfterSaleOrderCount"], 14)
        self.assertEqual(supplementary["costs"]["matchedCount"], 2434)
        self.assertEqual(supplementary["otherFunds"]["totalResultCount"], 265)

        cross_page = self.service.get_supplementary_results(
            task["id"], uploaded["file"]["id"], "cross_month", "needs_attention", 1, 20
        )
        self.assertEqual(cross_page["pagination"]["totalRows"], 115)
        cross_detail = self.service.get_supplementary_result(
            task["id"], uploaded["file"]["id"], "cross_month", cross_page["rows"][0]["id"]
        )["result"]
        self.assertEqual(cross_detail["source"]["sheetName"], "结算账单")
        self.assertIsNone(cross_detail["linkedSource"])

    def test_later_task_is_refreshed_when_historical_order_is_imported_afterwards(self):
        december_rows = {name: tuple(dict(row) for row in rows) for name, rows in DEFAULT_ROWS.items()}
        december_rows["订单明细"][0]["子订单编号"] = "2002"
        december_rows["订单明细"][0]["主订单编号"] = "MAIN2"
        december_rows["售后表"][0]["订单号"] = "MAIN2"
        december_rows["售后表"][0]["商品单号"] = "2002"
        december_task = self.service.create_task(
            {"entityName": "示例商贸公司", "storeName": "跨月回刷店", "period": "2023-12"}
        )
        december_upload = self.service.upload_workbook(
            december_task["id"], "12月.xlsx", build_workbook_bytes(rows_by_sheet=december_rows)
        )
        self.assertEqual(december_upload["task"]["status"], "needs_attention")
        self.assertEqual(
            december_upload["file"]["supplementaryReconciliation"]["crossMonth"]["missingHistoricalOrderCount"],
            1,
        )

        november_rows = {name: tuple(dict(row) for row in rows) for name, rows in DEFAULT_ROWS.items()}
        november_rows["订单明细"][0]["订单提交时间"] = "2023-11-01 10:00:00"
        november_rows["售后表"][0]["售后申请时间"] = "2023-11-02 10:00:00"
        november_rows["结算账单"][0]["结算时间"] = "2023-11-03 10:00:00"
        november_rows["资金账单"][0]["动账时间"] = "2023-11-03 10:00:00"
        november_task = self.service.create_task(
            {"entityName": "示例商贸公司", "storeName": "跨月回刷店", "period": "2023-11"}
        )
        self.service.upload_workbook(
            november_task["id"], "11月.xlsx", build_workbook_bytes(rows_by_sheet=november_rows)
        )

        refreshed = self.service.get_task(december_task["id"])
        self.assertEqual(refreshed["task"]["status"], "ready")
        self.assertEqual(
            refreshed["files"][0]["supplementaryReconciliation"]["crossMonth"]["historicalOrderFoundCount"],
            1,
        )
        cross_page = self.service.get_supplementary_results(
            december_task["id"], december_upload["file"]["id"], "cross_month", "all", 1, 20
        )
        history_row = next(
            row for row in cross_page["rows"] if row["status"] == "order_found_history"
        )
        cross_detail = self.service.get_supplementary_result(
            december_task["id"], december_upload["file"]["id"],
            "cross_month", history_row["id"],
        )["result"]
        self.assertEqual(cross_detail["linkedSource"]["taskId"], november_task["id"])
        with connect(self.database_path) as connection:
            refresh_log = connection.execute(
                """
                SELECT action FROM operation_logs
                WHERE task_id = ? AND action = 'supplementary_reconciliation_refreshed'
                """,
                (december_task["id"],),
            ).fetchone()
        self.assertIsNotNone(refresh_log)

    def test_period_mismatch_creates_corrected_task_without_overwriting_original(self):
        source_task = self.service.create_task(
            {"entityName": "示例商贸公司", "storeName": "抖店月份修正", "period": "2026-08"}
        )
        source_result = self.service.upload_workbook(
            source_task["id"], "月份错误.xlsx", build_workbook_bytes()
        )
        self.assertEqual(source_result["task"]["status"], "needs_attention")
        self.assertEqual(source_result["file"]["dataImportStatus"], "failed")
        period_issue = next(
            item for item in source_result["file"]["dataImport"]["issueGroups"]
            if item["code"] == "task_period_mismatch"
        )
        self.assertEqual(period_issue["rawValues"], ["2023-12"])

        corrected = self.service.correct_task_period(
            source_task["id"], {"targetPeriod": "2023-12"}
        )
        self.assertNotEqual(corrected["task"]["id"], source_task["id"])
        self.assertEqual(corrected["task"]["period"], "2023-12")
        self.assertEqual(corrected["task"]["status"], "ready")
        self.assertTrue(corrected["correction"]["preservedOriginalTask"])
        self.assertEqual(corrected["files"][0]["dataImportStatus"], "warning")
        self.assertEqual(corrected["files"][0]["amountCheckStatus"], "passed")
        self.assertEqual(corrected["files"][0]["reconciliationStatus"], "passed")

        original = self.service.get_task(source_task["id"])
        self.assertEqual(original["task"]["period"], "2026-08")
        self.assertEqual(original["task"]["status"], "needs_attention")
        self.assertEqual(original["files"][0]["id"], source_result["file"]["id"])
        self.assertEqual(original["files"][0]["dataImportStatus"], "failed")

        with connect(self.database_path) as connection:
            source_log = connection.execute(
                """
                SELECT action FROM operation_logs
                WHERE task_id = ? AND action = 'task_period_correction_created'
                """,
                (source_task["id"],),
            ).fetchone()
            corrected_log = connection.execute(
                """
                SELECT action FROM operation_logs
                WHERE task_id = ? AND action = 'task_created_from_period_correction'
                """,
                (corrected["task"]["id"],),
            ).fetchone()
        self.assertIsNotNone(source_log)
        self.assertIsNotNone(corrected_log)

        with self.assertRaises(ValidationError):
            self.service.correct_task_period(
                source_task["id"], {"targetPeriod": "2023-11"}
            )

    def test_sample_is_only_loaded_on_explicit_action_and_is_idempotent(self):
        self.assertEqual(self.service.list_tasks(), [])

        first = self.service.load_sample()
        self.assertTrue(first["created"])
        self.assertTrue(first["task"]["isSample"])
        self.assertEqual(first["task"]["storeName"], "抖店样例店铺")
        self.assertEqual(first["files"][0]["inspectionStatus"], "passed")

        second = self.service.load_sample()
        self.assertFalse(second["created"])
        self.assertEqual(second["task"]["id"], first["task"]["id"])
        self.assertEqual(len(self.service.list_tasks()), 1)
        self.assertEqual(len(second["files"]), 1)

    def test_manual_resolution_completion_and_reopen_keep_full_history(self):
        rows = {
            name: tuple(dict(row) for row in values)
            for name, values in DEFAULT_ROWS.items()
        }
        rows["订单明细"][0]["货号"] = ""
        task = self.service.create_task(
            {"entityName": "示例商贸公司", "storeName": "人工处理验证", "period": "2023-12"}
        )
        uploaded = self.service.upload_workbook(
            task["id"], "缺少货号.xlsx", build_workbook_bytes(rows_by_sheet=rows)
        )
        file_id = uploaded["file"]["id"]
        before = self.service.get_completion_summary(task["id"])["completion"]
        self.assertEqual(before["unresolvedCount"], 1)
        self.assertFalse(before["canComplete"])

        cost_page = self.service.get_supplementary_results(
            task["id"], file_id, "cost", "needs_attention", 1, 20
        )
        result_id = cost_page["rows"][0]["id"]
        first = self.service.save_manual_resolution(
            task["id"],
            file_id,
            "cost",
            result_id,
            {
                "actionType": "adjust_amount",
                "adjustedAmountCents": 650,
                "reason": "根据库存商品卡补录单件成本",
            },
        )
        self.assertEqual(first["manualResolution"]["adjustedAmountCents"], 650)
        self.assertTrue(first["completion"]["canComplete"])
        self.assertEqual(first["completion"]["resolvedCount"], 1)

        second = self.service.save_manual_resolution(
            task["id"],
            file_id,
            "cost",
            result_id,
            {
                "actionType": "carry_forward",
                "followUpDate": "2024-01-05",
                "reason": "等待平台补发正式商品编码",
            },
        )
        self.assertTrue(second["completion"]["canComplete"])
        self.assertEqual(second["completion"]["carriedForwardCount"], 1)
        detail = self.service.get_supplementary_result(
            task["id"], file_id, "cost", result_id
        )["result"]
        self.assertEqual(detail["status"], "missing_sku")
        self.assertEqual(detail["manualResolution"]["actionType"], "carry_forward")
        self.assertEqual(len(detail["manualHistory"]), 2)
        self.assertTrue(detail["manualHistory"][0]["isCurrent"])
        self.assertFalse(detail["manualHistory"][1]["isCurrent"])

        with self.assertRaises(ValidationError):
            self.service.complete_task(task["id"], {"confirmed": False})
        completed = self.service.complete_task(
            task["id"], {"confirmed": True, "note": "已核对汇总并确认完成"}
        )
        self.assertEqual(completed["task"]["status"], "completed")
        self.assertEqual(completed["lifecycleEvents"][0]["action"], "completed")
        with self.assertRaises(ValidationError):
            self.service.save_manual_resolution(
                task["id"],
                file_id,
                "cost",
                result_id,
                {"actionType": "confirm", "reason": "尝试修改已完成期间"},
            )
        with self.assertRaises(ValidationError):
            self.service.reopen_task(task["id"], {"reason": ""})

        reopened = self.service.reopen_task(
            task["id"], {"reason": "收到新的商品编码，需要重新处理"}
        )
        self.assertEqual(reopened["task"]["status"], "reopened")
        self.assertTrue(reopened["completion"]["canComplete"])
        self.assertEqual(
            [item["action"] for item in reopened["lifecycleEvents"][:2]],
            ["reopened", "completed"],
        )

    def test_manual_candidate_must_belong_to_current_result(self):
        rows = {
            name: tuple(dict(row) for row in values)
            for name, values in DEFAULT_ROWS.items()
        }
        rows["资金账单"] = (
            dict(rows["资金账单"][0]),
            dict(rows["资金账单"][0]),
        )
        rows["资金账单"][1]["动帐流水号"] = "FUN2"
        task = self.service.create_task(
            {"entityName": "示例商贸公司", "storeName": "候选选择验证", "period": "2023-12"}
        )
        uploaded = self.service.upload_workbook(
            task["id"], "多候选.xlsx", build_workbook_bytes(rows_by_sheet=rows)
        )
        file_id = uploaded["file"]["id"]
        page = self.service.get_reconciliation_results(
            task["id"], file_id, "needs_attention", 1, 20
        )
        result_id = page["rows"][0]["id"]
        with self.assertRaises(ValidationError):
            self.service.save_manual_resolution(
                task["id"],
                file_id,
                "ordinary_settlement",
                result_id,
                {
                    "actionType": "select_candidate",
                    "selectedCandidateKey": "NOT-IN-RESULT",
                    "reason": "验证越权候选会被拒绝",
                },
            )
        saved = self.service.save_manual_resolution(
            task["id"],
            file_id,
            "ordinary_settlement",
            result_id,
            {
                "actionType": "select_candidate",
                "selectedCandidateKey": "FUN2",
                "reason": "以平台流水号FUN2作为有效入账",
            },
        )
        self.assertEqual(saved["manualResolution"]["selectedCandidateKey"], "FUN2")
        refreshed = self.service.get_reconciliation_results(
            task["id"], file_id, "needs_attention", 1, 20
        )
        self.assertEqual(
            refreshed["rows"][0]["manualResolution"]["actionType"],
            "select_candidate",
        )


if __name__ == "__main__":
    unittest.main()
