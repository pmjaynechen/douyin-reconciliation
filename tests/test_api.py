import json
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from urllib.parse import unquote

from recon_app.api import ApiApplication
from recon_app.database import connect, initialize_database
from recon_app.services import ReconciliationService
from xlsx_fixture import (
    DEFAULT_ROWS,
    build_operating_evidence_workbook_bytes,
    build_workbook_bytes,
)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "api.db"
        sample_path = Path(self.temp_dir.name) / "sample.xlsx"
        sample_path.write_bytes(build_workbook_bytes())
        initialize_database(database_path)
        self.api = ApiApplication(
            ReconciliationService(database_path, sample_workbook_path=sample_path)
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def decode(self, response):
        return response[0], json.loads(response[2].decode("utf-8"))

    def test_health_endpoint(self):
        status, payload = self.decode(self.api.handle("GET", "/api/health"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["database"], "ok")

    def test_configuration_template_lifecycle_endpoints(self):
        status, configuration = self.decode(
            self.api.handle("GET", "/api/configuration")
        )
        self.assertEqual(status, 200)
        self.assertEqual(configuration["currentTemplate"]["versionLabel"], "V1.0")
        self.assertEqual(len(configuration["rules"]), 13)

        status, created = self.decode(
            self.api.handle("POST", "/api/configuration/templates/drafts")
        )
        self.assertEqual(status, 201)
        draft_id = created["template"]["id"]

        status, tested = self.decode(
            self.api.handle(
                "POST",
                "/api/configuration/templates/{}/test".format(draft_id),
                build_workbook_bytes(),
                {"X-File-Name": "%E5%B9%B3%E5%8F%B0%E6%A0%B7%E4%BE%8B.xlsx"},
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(tested["inspection"]["status"], "passed")

        status, activated = self.decode(
            self.api.handle(
                "POST",
                "/api/configuration/templates/{}/activate".format(draft_id),
                json.dumps({"confirmed": True}).encode("utf-8"),
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(activated["currentTemplate"]["id"], draft_id)
        self.assertEqual(activated["currentTemplate"]["versionLabel"], "V1.1")

    def test_configuration_rule_lifecycle_endpoints(self):
        status, created = self.decode(
            self.api.handle("POST", "/api/configuration/rules/drafts")
        )
        self.assertEqual(status, 201)
        draft_id = created["rule"]["id"]
        payload = {
            "toleranceCents": 2,
            "refundAutoGroupSeconds": 600,
            "refundCandidateSeconds": 172800,
            "settlementWaitDays": 10,
            "notes": "接口规则发布验收",
        }
        status, updated = self.decode(
            self.api.handle(
                "POST", "/api/configuration/rules/{}".format(draft_id),
                json.dumps(payload).encode("utf-8"),
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["rule"]["toleranceCents"], 2)

        status, tested = self.decode(
            self.api.handle(
                "POST", "/api/configuration/rules/{}/test".format(draft_id)
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(tested["fixedCases"]["passedCount"], 23)

        status, activated = self.decode(
            self.api.handle(
                "POST", "/api/configuration/rules/{}/activate".format(draft_id),
                json.dumps({"confirmed": True}).encode("utf-8"),
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(activated["currentRule"]["versionLabel"], "V1.2")
        self.assertEqual(activated["currentRule"]["fixedCases"]["passedCount"], 23)

    def test_master_data_and_platform_value_mapping_endpoints(self):
        status, entities = self.decode(
            self.api.handle(
                "POST", "/api/configuration/entities",
                json.dumps({"name": "接口主体"}).encode("utf-8"),
            )
        )
        self.assertEqual(status, 201)
        entity_id = entities["entities"][0]["id"]
        status, stores = self.decode(
            self.api.handle(
                "POST", "/api/configuration/stores",
                json.dumps({"entityId": entity_id, "name": "接口店铺"}).encode("utf-8"),
            )
        )
        self.assertEqual(status, 201)
        store_id = stores["entities"][0]["stores"][0]["id"]
        status, task = self.decode(
            self.api.handle(
                "POST", "/api/tasks",
                json.dumps({"storeId": store_id, "period": "2023-12"}).encode("utf-8"),
            )
        )
        self.assertEqual(status, 201)
        self.assertEqual(task["task"]["storeName"], "接口店铺")

        status, mapping = self.decode(
            self.api.handle(
                "POST", "/api/configuration/value-mappings",
                json.dumps({
                    "mappingType": "fund_scene",
                    "sourceValue": "接口新场景",
                    "standardCode": "withdrawal",
                    "effectiveFrom": "2026-08-01",
                    "notes": "接口测试确认是平台提现",
                }).encode("utf-8"),
            )
        )
        self.assertEqual(status, 201)
        current = next(
            item for item in mapping["valueMappings"]
            if item["sourceValue"] == "接口新场景" and item["isCurrent"]
        )
        self.assertEqual(current["standardCode"], "withdrawal")

        status, disabled = self.decode(
            self.api.handle(
                "POST", "/api/configuration/stores/{}/status".format(store_id),
                json.dumps({"status": "inactive"}).encode("utf-8"),
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(disabled["entities"][0]["stores"][0]["status"], "inactive")

    def test_task_endpoints(self):
        body = json.dumps(
            {"entityName": "示例商贸公司", "storeName": "抖店A店", "period": "2023-12"}
        ).encode("utf-8")
        status, created = self.decode(self.api.handle("POST", "/api/tasks", body))
        self.assertEqual(status, 201)
        self.assertEqual(created["task"]["period"], "2023-12")

        status, listed = self.decode(self.api.handle("GET", "/api/tasks"))
        self.assertEqual(status, 200)
        self.assertEqual(len(listed["tasks"]), 1)

        status, duplicate = self.decode(self.api.handle("POST", "/api/tasks", body))
        self.assertEqual(status, 409)
        self.assertEqual(duplicate["existingTask"]["id"], created["task"]["id"])

    def test_operating_report_readiness_endpoint(self):
        task_body = json.dumps(
            {"entityName": "接口主体", "storeName": "报表接口店", "period": "2023-12"}
        ).encode("utf-8")
        _, created = self.decode(self.api.handle("POST", "/api/tasks", task_body))
        task_id = created["task"]["id"]
        status, empty = self.decode(
            self.api.handle("GET", "/api/tasks/{}/operating-report-readiness".format(task_id))
        )
        self.assertEqual(status, 200)
        self.assertEqual(empty["status"], "no_import")

        status, _ = self.decode(
            self.api.handle(
                "POST",
                "/api/tasks/{}/files".format(task_id),
                build_workbook_bytes(),
                {"X-File-Name": "%E7%BB%8F%E8%90%A5%E6%8A%A5%E8%A1%A8.xlsx"},
            )
        )
        self.assertEqual(status, 201)
        status, report = self.decode(
            self.api.handle("GET", "/api/tasks/{}/operating-report-readiness".format(task_id))
        )
        self.assertEqual(status, 200)
        self.assertEqual(report["summary"]["settlementNetCents"], 1000)
        self.assertFalse(report["completeness"]["canIssueProfit"])

    def test_operating_evidence_upload_and_query_endpoints(self):
        body = json.dumps(
            {"entityName": "接口主体", "storeName": "经营资料接口店", "period": "2023-12"}
        ).encode("utf-8")
        _, created = self.decode(self.api.handle("POST", "/api/tasks", body))
        task_id = created["task"]["id"]
        status, uploaded = self.decode(
            self.api.handle(
                "POST",
                "/api/tasks/{}/operating-evidence/fulfillment_expense/files".format(task_id),
                b"tracking_no,amount\nSF001,12.30\n",
                {"X-File-Name": "%E5%BF%AB%E9%80%92%E8%B4%A6%E5%8D%95.csv"},
            )
        )
        self.assertEqual(status, 201)
        self.assertEqual(uploaded["operatingEvidence"]["receivedTypeCount"], 1)

        status, queried = self.decode(
            self.api.handle("GET", "/api/tasks/{}/operating-evidence".format(task_id))
        )
        self.assertEqual(status, 200)
        fulfillment = next(
            item for item in queried["operatingEvidence"]["categories"]
            if item["code"] == "fulfillment_expense"
        )
        self.assertEqual(fulfillment["latestFile"]["originalName"], "快递账单.csv")

    def test_simulated_operating_profit_and_detail_endpoint(self):
        _, sample = self.decode(self.api.handle("POST", "/api/sample/load"))
        task_id = sample["task"]["id"]
        workbook = build_operating_evidence_workbook_bytes(task_id)
        for evidence_type in ("erp_cost", "fulfillment_expense", "operating_expense"):
            status, _ = self.decode(self.api.handle(
                "POST",
                "/api/tasks/{}/operating-evidence/{}/files".format(task_id, evidence_type),
                workbook,
                {"X-File-Name": "%E7%BB%8F%E8%90%A5%E6%A8%A1%E6%8B%9F%E8%B5%84%E6%96%99.xlsx"},
            ))
            self.assertEqual(status, 201)

        status, report = self.decode(self.api.handle(
            "GET", "/api/tasks/{}/operating-report-readiness".format(task_id)
        ))
        self.assertEqual(status, 200)
        self.assertEqual(report["status"], "trial_ready")
        self.assertEqual(report["profitTrial"]["amountCents"], 750)

        status, detail = self.decode(self.api.handle(
            "GET",
            "/api/tasks/{}/operating-evidence/erp_cost/results?page=1&pageSize=50".format(task_id),
        ))
        self.assertEqual(status, 200)
        self.assertEqual(detail["pagination"]["total"], 1)
        self.assertEqual(detail["rows"][0]["status"], "matched")

    def test_invalid_json_and_missing_route(self):
        status, payload = self.decode(self.api.handle("POST", "/api/tasks", b"not-json"))
        self.assertEqual(status, 400)
        self.assertIn("JSON", payload["error"])

        status, payload = self.decode(self.api.handle("GET", "/api/unknown"))
        self.assertEqual(status, 404)

    def test_platform_balance_trial_upload_and_result_endpoints(self):
        body = json.dumps(
            {"entityName": "测试主体", "storeName": "M017接口店", "period": "2026-07"}
        ).encode("utf-8")
        _, created = self.decode(self.api.handle("POST", "/api/tasks", body))
        task_id = created["task"]["id"]
        project_root = Path(__file__).resolve().parents[3]
        workbook_path = (
            project_root / "对账文件" / "抖店测试数据" /
            "抖店M017-M018模拟测试数据.xlsx"
        )
        status, uploaded = self.decode(
            self.api.handle(
                "POST",
                "/api/tasks/{}/platform-balance-files".format(task_id),
                workbook_path.read_bytes(),
                {"X-File-Name": "%E6%8A%96%E5%BA%97M017%E6%A8%A1%E6%8B%9F.xlsx"},
            )
        )
        self.assertEqual(status, 201)
        self.assertEqual(uploaded["platformBalance"]["run"]["attentionCount"], 9)
        self.assertFalse(uploaded["platformBalance"]["blockingCompletion"])

        status, results = self.decode(
            self.api.handle(
                "GET",
                "/api/tasks/{}/platform-balance-results?status=attention&page=1&pageSize=20".format(task_id),
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(results["pagination"]["totalRows"], 9)
        self.assertEqual(results["summary"]["mappingVersion"], "M017-SIM-1")
        self.assertTrue(results["rows"][0]["source"]["values"])

    def test_pending_settlement_trial_upload_and_result_endpoints(self):
        body = json.dumps(
            {"entityName": "测试主体", "storeName": "M018接口店", "period": "2026-08"}
        ).encode("utf-8")
        _, created = self.decode(self.api.handle("POST", "/api/tasks", body))
        task_id = created["task"]["id"]
        project_root = Path(__file__).resolve().parents[3]
        workbook_path = (
            project_root / "对账文件" / "抖店测试数据" /
            "抖店M017-M018模拟测试数据.xlsx"
        )
        status, uploaded = self.decode(
            self.api.handle(
                "POST",
                "/api/tasks/{}/pending-settlement-files".format(task_id),
                workbook_path.read_bytes(),
                {"X-File-Name": "%E6%8A%96%E5%BA%97M018%E6%A8%A1%E6%8B%9F.xlsx"},
            )
        )
        self.assertEqual(status, 201)
        self.assertEqual(uploaded["pendingSettlement"]["run"]["attentionCount"], 6)
        self.assertFalse(uploaded["pendingSettlement"]["blockingCompletion"])

        status, results = self.decode(
            self.api.handle(
                "GET",
                "/api/tasks/{}/pending-settlement-results?status=attention&page=1&pageSize=20".format(task_id),
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(results["pagination"]["totalRows"], 6)
        self.assertEqual(results["summary"]["mappingVersion"], "M018-SIM-1")
        self.assertTrue(results["rows"][0]["source"]["values"])

    def test_workbook_upload_and_task_detail_endpoints(self):
        body = json.dumps(
            {"entityName": "示例商贸公司", "storeName": "抖店A店", "period": "2023-12"}
        ).encode("utf-8")
        status, created = self.decode(self.api.handle("POST", "/api/tasks", body))
        task_id = created["task"]["id"]

        workbook = build_workbook_bytes()
        status, uploaded = self.decode(
            self.api.handle(
                "POST",
                "/api/tasks/{}/files".format(task_id),
                workbook,
                {"X-File-Name": "%E6%8A%96%E5%BA%97%E7%BB%83%E4%B9%A0%E6%95%B0%E6%8D%AE.xlsx"},
            )
        )
        self.assertEqual(status, 201)
        self.assertEqual(uploaded["task"]["status"], "ready")
        self.assertEqual(uploaded["file"]["inspection"]["foundRequiredSheetCount"], 5)

        status, detail = self.decode(
            self.api.handle("GET", "/api/tasks/{}".format(task_id))
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(detail["files"]), 1)

        file_id = uploaded["file"]["id"]
        status, records = self.decode(
            self.api.handle(
                "GET",
                "/api/tasks/{}/files/{}/records?sheet=%E8%AE%A2%E5%8D%95%E6%98%8E%E7%BB%86&page=1&pageSize=20".format(
                    task_id, file_id
                ),
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(records["sheetName"], "订单明细")
        self.assertEqual(records["pagination"]["totalRows"], 1)
        self.assertEqual(records["rows"][0]["values"]["subOrderId"], "1001")

        status, reconciliation = self.decode(
            self.api.handle(
                "GET",
                "/api/tasks/{}/files/{}/reconciliation-results?status=all&page=1&pageSize=20".format(
                    task_id, file_id
                ),
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(reconciliation["summary"]["matchedCount"], 1)
        self.assertEqual(reconciliation["rows"][0]["statusLabel"], "核对一致")

        result_id = reconciliation["rows"][0]["id"]
        status, result_detail = self.decode(
            self.api.handle(
                "GET",
                "/api/tasks/{}/files/{}/reconciliation-results/{}".format(
                    task_id, file_id, result_id
                ),
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(result_detail["result"]["settlementSource"]["sheetName"], "结算账单")
        self.assertEqual(result_detail["result"]["fundSource"]["sheetName"], "资金账单")

        status, refunds = self.decode(
            self.api.handle(
                "GET",
                "/api/tasks/{}/files/{}/refund-reconciliation-results?status=all&page=1&pageSize=20".format(
                    task_id, file_id
                ),
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(refunds["resultType"], "refund_settlement")
        self.assertEqual(refunds["summary"]["totalResultCount"], 0)

        status, costs = self.decode(
            self.api.handle(
                "GET",
                "/api/tasks/{}/files/{}/supplementary-results/cost?status=all&page=1&pageSize=20".format(
                    task_id, file_id
                ),
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(costs["resultType"], "cost")
        self.assertEqual(costs["summary"]["matchedCount"], 1)
        cost_result_id = costs["rows"][0]["id"]
        status, cost_detail = self.decode(
            self.api.handle(
                "GET",
                "/api/tasks/{}/files/{}/supplementary-results/cost/{}".format(
                    task_id, file_id, cost_result_id
                ),
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(cost_detail["result"]["source"]["sheetName"], "订单明细")
        self.assertEqual(cost_detail["result"]["linkedSource"]["sheetName"], "成本表")

        status, invalid_page = self.decode(
            self.api.handle(
                "GET",
                "/api/tasks/{}/files/{}/records?sheet=%E8%AE%A2%E5%8D%95%E6%98%8E%E7%BB%86&page=0&pageSize=20".format(
                    task_id, file_id
                ),
            )
        )
        self.assertEqual(status, 400)
        self.assertIn("页码", invalid_page["error"])

        status, duplicate = self.decode(
            self.api.handle(
                "POST",
                "/api/tasks/{}/files".format(task_id),
                workbook,
                {"X-File-Name": "same.xlsx"},
            )
        )
        self.assertEqual(status, 409)
        self.assertEqual(duplicate["existingFile"]["id"], uploaded["file"]["id"])

    def test_wide_reconciliation_endpoint_combines_sources_and_supports_filters(self):
        body = json.dumps(
            {"entityName": "宽表主体", "storeName": "宽表店铺", "period": "2023-12"}
        ).encode("utf-8")
        _, created = self.decode(self.api.handle("POST", "/api/tasks", body))
        task_id = created["task"]["id"]
        rows = {
            name: tuple(dict(row) for row in values)
            for name, values in DEFAULT_ROWS.items()
        }
        second_after_sale = dict(rows["售后表"][0])
        second_after_sale["售后单号"] = "AF2"
        second_after_sale["退商品金额（元）"] = "2.00"
        second_after_sale["售后状态"] = "售后关闭"
        rows["售后表"] = (rows["售后表"][0], second_after_sale)
        standalone_fund = {
            "动账时间": "2023-12-04 10:00:00",
            "动帐流水号": "OTHER1",
            "动账方向": "入账",
            "动账金额": "3.00",
            "动账账户": "聚合账户",
            "动账场景": "消费者赔付",
            "子订单号": "",
        }
        rows["资金账单"] = (rows["资金账单"][0], standalone_fund)
        status, uploaded = self.decode(
            self.api.handle(
                "POST",
                "/api/tasks/{}/files".format(task_id),
                build_workbook_bytes(rows_by_sheet=rows),
                {"X-File-Name": "wide.xlsx"},
            )
        )
        self.assertEqual(status, 201)
        file_id = uploaded["file"]["id"]

        status, wide = self.decode(
            self.api.handle(
                "GET",
                "/api/tasks/{}/files/{}/wide-reconciliation-results?status=all&scene=all&page=1&pageSize=20".format(
                    task_id, file_id
                ),
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(wide["summary"]["totalRowCount"], 2)
        order_row = next(item for item in wide["rows"] if item["subOrderId"] == "1001")
        self.assertEqual(order_row["afterSaleCount"], 2)
        self.assertEqual(order_row["afterSaleIds"], ["AF1", "AF2"])
        self.assertEqual(order_row["settlementCount"], 1)
        self.assertEqual(order_row["fundCount"], 1)
        self.assertEqual(order_row["expectedMerchantReceivableCents"], 1000)
        self.assertEqual(order_row["afterSaleRequestedRefundCents"], 1200)
        self.assertEqual(order_row["afterSaleRefundCents"], 1000)
        self.assertEqual(order_row["unitCostCents"], 650)
        self.assertIn("ordinary_settlement", order_row["sceneKeys"])
        self.assertIn("cost", order_row["sceneKeys"])

        status, searched = self.decode(
            self.api.handle(
                "GET",
                "/api/tasks/{}/files/{}/wide-reconciliation-results?query=OTHER1&scene=other_fund&page=1&pageSize=20".format(
                    task_id, file_id
                ),
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(searched["pagination"]["totalRows"], 1)
        self.assertIsNone(searched["rows"][0]["subOrderId"])
        self.assertEqual(searched["rows"][0]["fundTransactionIds"], ["OTHER1"])
        self.assertEqual(searched["rows"][0]["status"], "source_only")

        status, invalid = self.decode(
            self.api.handle(
                "GET",
                "/api/tasks/{}/files/{}/wide-reconciliation-results?scene=unknown".format(
                    task_id, file_id
                ),
            )
        )
        self.assertEqual(status, 400)
        self.assertIn("场景", invalid["error"])

    def test_sample_endpoint_requires_explicit_post_and_does_not_duplicate(self):
        status, listed = self.decode(self.api.handle("GET", "/api/tasks"))
        self.assertEqual(status, 200)
        self.assertEqual(listed["tasks"], [])

        status, first = self.decode(self.api.handle("POST", "/api/sample/load"))
        self.assertEqual(status, 201)
        self.assertTrue(first["created"])
        self.assertTrue(first["task"]["isSample"])

        status, second = self.decode(self.api.handle("POST", "/api/sample/load"))
        self.assertEqual(status, 200)
        self.assertFalse(second["created"])
        self.assertEqual(second["task"]["id"], first["task"]["id"])

    def test_period_correction_endpoint_creates_audited_task(self):
        body = json.dumps(
            {"entityName": "示例商贸公司", "storeName": "接口月份修正", "period": "2026-08"}
        ).encode("utf-8")
        status, created = self.decode(self.api.handle("POST", "/api/tasks", body))
        self.assertEqual(status, 201)
        source_task_id = created["task"]["id"]

        status, uploaded = self.decode(
            self.api.handle(
                "POST",
                "/api/tasks/{}/files".format(source_task_id),
                build_workbook_bytes(),
                {"X-File-Name": "period.xlsx"},
            )
        )
        self.assertEqual(status, 201)
        self.assertEqual(uploaded["file"]["dataImportStatus"], "failed")

        correction_body = json.dumps({"targetPeriod": "2023-12"}).encode("utf-8")
        status, corrected = self.decode(
            self.api.handle(
                "POST",
                "/api/tasks/{}/correct-period".format(source_task_id),
                correction_body,
            )
        )
        self.assertEqual(status, 201)
        self.assertEqual(corrected["task"]["period"], "2023-12")
        self.assertEqual(corrected["task"]["status"], "ready")
        self.assertTrue(corrected["correction"]["preservedOriginalTask"])

    def test_manual_resolution_completion_and_reopen_endpoints(self):
        body = json.dumps(
            {"entityName": "示例商贸公司", "storeName": "接口人工处理", "period": "2023-12"}
        ).encode("utf-8")
        _, created = self.decode(self.api.handle("POST", "/api/tasks", body))
        task_id = created["task"]["id"]
        rows = {
            name: tuple(dict(row) for row in values)
            for name, values in DEFAULT_ROWS.items()
        }
        rows["订单明细"][0]["货号"] = ""
        status, uploaded = self.decode(
            self.api.handle(
                "POST",
                "/api/tasks/{}/files".format(task_id),
                build_workbook_bytes(rows_by_sheet=rows),
                {"X-File-Name": "manual.xlsx"},
            )
        )
        self.assertEqual(status, 201)
        file_id = uploaded["file"]["id"]
        _, costs = self.decode(
            self.api.handle(
                "GET",
                "/api/tasks/{}/files/{}/supplementary-results/cost?status=needs_attention&page=1&pageSize=20".format(
                    task_id, file_id
                ),
            )
        )
        result_id = costs["rows"][0]["id"]
        manual_body = json.dumps(
            {
                "actionType": "confirm",
                "reason": "线下已核对商品成本资料",
            }
        ).encode("utf-8")
        status, saved = self.decode(
            self.api.handle(
                "POST",
                "/api/tasks/{}/files/{}/results/cost/{}/manual-resolution".format(
                    task_id, file_id, result_id
                ),
                manual_body,
            )
        )
        self.assertEqual(status, 200)
        self.assertTrue(saved["completion"]["canComplete"])

        status, preview = self.decode(
            self.api.handle("GET", "/api/tasks/{}/completion".format(task_id))
        )
        self.assertEqual(status, 200)
        self.assertEqual(preview["completion"]["unresolvedCount"], 0)
        complete_body = json.dumps({"confirmed": True}).encode("utf-8")
        status, completed = self.decode(
            self.api.handle(
                "POST", "/api/tasks/{}/complete".format(task_id), complete_body
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(completed["task"]["status"], "completed")

        reopen_body = json.dumps(
            {"reason": "平台补发了新的账单资料"}
        ).encode("utf-8")
        status, reopened = self.decode(
            self.api.handle(
                "POST", "/api/tasks/{}/reopen".format(task_id), reopen_body
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(reopened["task"]["status"], "reopened")

    def test_result_export_uses_current_filter_and_typed_xlsx_cells(self):
        body = json.dumps(
            {"entityName": "示例商贸公司", "storeName": "导出验收店", "period": "2023-12"}
        ).encode("utf-8")
        _, created = self.decode(self.api.handle("POST", "/api/tasks", body))
        task_id = created["task"]["id"]
        rows = {
            name: tuple(dict(row) for row in values)
            for name, values in DEFAULT_ROWS.items()
        }
        long_sub_order = "6923914228418287413"
        long_transaction = "146188259890014994"
        rows["订单明细"][0]["子订单编号"] = long_sub_order
        rows["售后表"][0]["商品单号"] = long_sub_order
        rows["结算账单"][0]["子订单号"] = long_sub_order
        rows["资金账单"][0]["子订单号"] = long_sub_order
        rows["资金账单"][0]["动帐流水号"] = long_transaction
        _, uploaded = self.decode(
            self.api.handle(
                "POST",
                "/api/tasks/{}/files".format(task_id),
                build_workbook_bytes(rows_by_sheet=rows),
                {"X-File-Name": "export.xlsx"},
            )
        )
        file_id = uploaded["file"]["id"]

        status, headers, content = self.api.handle(
            "GET",
            "/api/tasks/{}/files/{}/exports/ordinary_settlement.xlsx?status=all".format(
                task_id, file_id
            ),
        )
        self.assertEqual(status, 200)
        self.assertIn("spreadsheetml.sheet", headers["Content-Type"])
        self.assertIn("filename*=UTF-8''", headers["Content-Disposition"])
        self.assertTrue(content.startswith(b"PK"))
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            result_xml = archive.read("xl/worksheets/sheet2.xml").decode("utf-8")
            metadata_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn(long_sub_order, result_xml)
        self.assertIn(long_transaction, result_xml)
        self.assertIn('s="2"><v>10</v>', result_xml)
        self.assertEqual(result_xml.count("<row "), 2)
        self.assertIn("当前结果页筛选下的全部明细", metadata_xml)

        status, _, filtered_content = self.api.handle(
            "GET",
            "/api/tasks/{}/files/{}/exports/ordinary_settlement.xlsx?status=needs_attention".format(
                task_id, file_id
            ),
        )
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(filtered_content)) as archive:
            filtered_xml = archive.read("xl/worksheets/sheet2.xml").decode("utf-8")
        self.assertEqual(filtered_xml.count("<row "), 1)

        for result_type in (
            "refund_settlement",
            "cross_month",
            "after_sale",
            "cost",
            "other_fund",
        ):
            status, _, exported_content = self.api.handle(
                "GET",
                "/api/tasks/{}/files/{}/exports/{}.xlsx?status=all".format(
                    task_id, file_id, result_type
                ),
            )
            self.assertEqual(status, 200, result_type)
            self.assertTrue(exported_content.startswith(b"PK"), result_type)

    def test_wide_export_inherits_status_scene_and_search_filters(self):
        body = json.dumps(
            {"entityName": "示例商贸公司", "storeName": "宽表导出店", "period": "2023-12"}
        ).encode("utf-8")
        _, created = self.decode(self.api.handle("POST", "/api/tasks", body))
        task_id = created["task"]["id"]
        rows = {
            name: tuple(dict(row) for row in values)
            for name, values in DEFAULT_ROWS.items()
        }
        long_sub_order = "6923914228418287413"
        long_transaction = "146188259890014994"
        rows["订单明细"][0]["子订单编号"] = long_sub_order
        rows["售后表"][0]["商品单号"] = long_sub_order
        rows["结算账单"][0]["子订单号"] = long_sub_order
        rows["资金账单"][0]["子订单号"] = long_sub_order
        rows["资金账单"][0]["动帐流水号"] = long_transaction
        _, uploaded = self.decode(
            self.api.handle(
                "POST",
                "/api/tasks/{}/files".format(task_id),
                build_workbook_bytes(rows_by_sheet=rows),
                {"X-File-Name": "wide-export.xlsx"},
            )
        )
        file_id = uploaded["file"]["id"]

        status, headers, content = self.api.handle(
            "GET",
            (
                "/api/tasks/{}/files/{}/exports/wide_reconciliation.xlsx"
                "?status=all&scene=ordinary_settlement&query={}"
            ).format(task_id, file_id, long_sub_order),
        )
        self.assertEqual(status, 200)
        self.assertIn("对账明细宽表", unquote(headers["Content-Disposition"]))
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            result_xml = archive.read("xl/worksheets/sheet2.xml").decode("utf-8")
            metadata_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertEqual(result_xml.count("<row "), 2)
        self.assertIn("核对-各规则结论", result_xml)
        self.assertIn("追溯-来源Excel行", result_xml)
        self.assertIn(long_sub_order, result_xml)
        self.assertIn(long_transaction, result_xml)
        self.assertIn("订单明细!第2行", result_xml)
        self.assertIn("普通结算", metadata_xml)
        self.assertIn(long_sub_order, metadata_xml)
        self.assertIn("不受页面分页限制", metadata_xml)

        with connect(self.api.service.database_path) as connection:
            operation = connection.execute(
                """
                SELECT details_json FROM operation_logs
                WHERE task_id = ? AND action = 'results_exported'
                ORDER BY id DESC LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        details = json.loads(operation["details_json"])
        self.assertEqual(details["resultType"], "wide_reconciliation")
        self.assertEqual(details["scene"], "ordinary_settlement")
        self.assertEqual(details["query"], long_sub_order)
        self.assertEqual(details["rowCount"], 1)

        status, invalid = self.decode(
            self.api.handle(
                "GET",
                "/api/tasks/{}/files/{}/exports/wide_reconciliation.xlsx?scene=unsupported".format(
                    task_id, file_id
                ),
            )
        )
        self.assertEqual(status, 400)
        self.assertIn("场景", invalid["error"])


if __name__ == "__main__":
    unittest.main()
