import tempfile
import unittest
from pathlib import Path

from recon_app.data_import import analyze_workbook_data
from recon_app.settlement_reconciliation import (
    calculate_ordinary_settlement_reconciliation,
)
from recon_app.refund_reconciliation import calculate_refund_settlement_reconciliation
from xlsx_fixture import DEFAULT_ROWS, build_workbook_bytes


class SettlementReconciliationTests(unittest.TestCase):
    def analyze(self, rows_by_sheet=None):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "input.xlsx"
            path.write_bytes(build_workbook_bytes(rows_by_sheet=rows_by_sheet))
            imported = analyze_workbook_data(path, "2023-12")
            return calculate_ordinary_settlement_reconciliation(imported["records"], 1)

    def test_unique_sub_order_scene_and_amount_match_passes(self):
        result = self.analyze()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["totalResultCount"], 1)
        self.assertEqual(result["matchedCount"], 1)
        self.assertEqual(result["settlementAmountTotalCents"], 1000)
        self.assertEqual(result["matchedFundAmountTotalCents"], 1000)
        self.assertEqual(result["results"][0]["fundTransactionId"], "FUN1")

    def test_one_cent_passes_and_two_cents_is_an_amount_difference(self):
        one_cent = dict(DEFAULT_ROWS["资金账单"][0])
        one_cent["动账金额"] = "10.01"
        result = self.analyze({"资金账单": (one_cent,)})
        self.assertEqual(result["matchedCount"], 1)
        self.assertEqual(result["results"][0]["differenceCents"], 1)

        two_cents = dict(one_cent)
        two_cents["动账金额"] = "10.02"
        result = self.analyze({"资金账单": (two_cents,)})
        self.assertEqual(result["status"], "needs_attention")
        self.assertEqual(result["results"][0]["status"], "amount_mismatch")
        self.assertEqual(result["results"][0]["differenceCents"], 2)

    def test_missing_and_multiple_candidates_stop_automatic_matching(self):
        result = self.analyze({"资金账单": ()})
        self.assertEqual(result["results"][0]["status"], "missing_fund")

        second = dict(DEFAULT_ROWS["资金账单"][0])
        second["动帐流水号"] = "FUN2"
        result = self.analyze(
            {"资金账单": (DEFAULT_ROWS["资金账单"][0], second)}
        )
        self.assertEqual(result["results"][0]["status"], "multiple_candidates")
        self.assertEqual(result["results"][0]["candidateCount"], 2)

    def test_same_sub_order_and_amount_with_wrong_scene_does_not_pass(self):
        wrong_scene = dict(DEFAULT_ROWS["资金账单"][0])
        wrong_scene["动账场景"] = "提现"
        result = self.analyze({"资金账单": (wrong_scene,)})
        self.assertEqual(result["matchedCount"], 0)
        self.assertEqual(result["results"][0]["status"], "missing_fund")

    def test_other_settlement_types_are_not_mixed_into_ordinary_settlement(self):
        refund = dict(DEFAULT_ROWS["结算账单"][0])
        refund["结算单类型"] = "结算后退款-原路退回"
        result = self.analyze({"结算账单": (refund,)})
        self.assertEqual(result["totalResultCount"], 0)

    def test_real_workbook_matches_ordinary_settlement_baseline(self):
        project_root = Path(__file__).resolve().parents[3]
        workbook_path = project_root / "对账文件" / "抖店练习数据.xlsx"
        imported = analyze_workbook_data(workbook_path, "2023-12")
        result = calculate_ordinary_settlement_reconciliation(imported["records"], 1)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["totalResultCount"], 375)
        self.assertEqual(result["matchedCount"], 375)
        self.assertEqual(result["attentionCount"], 0)
        self.assertEqual(result["settlementAmountTotalCents"], 58884824)
        self.assertEqual(result["matchedFundAmountTotalCents"], 58884824)
        self.assertEqual(result["differenceTotalCents"], 0)

    def test_real_workbook_matches_refund_net_group_baseline(self):
        project_root = Path(__file__).resolve().parents[3]
        workbook_path = project_root / "对账文件" / "抖店练习数据.xlsx"
        imported = analyze_workbook_data(workbook_path, "2023-12")
        result = calculate_refund_settlement_reconciliation(
            imported["records"], 1, 300, 86400
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["totalResultCount"], 6)
        self.assertEqual(result["matchedCount"], 6)
        self.assertEqual(result["settlementAmountTotalCents"], -1158760)
        self.assertEqual(result["matchedFundAmountTotalCents"], -1158760)
        self.assertEqual(result["differenceTotalCents"], 0)
        self.assertTrue(all(item["selectedRecords"] for item in result["results"]))

    def test_refund_time_boundaries_and_multiple_groups_stop_auto_grouping(self):
        def settlement():
            return {
                "recordType": "settlement",
                "rowNumber": 3,
                "primaryIdentifier": "SUB1",
                "eventTime": "2023-12-01T10:00:00",
                "amountCents": -1000,
                "rawValuesJson": {"结算单类型": "结算后退款-原路退回"},
            }

        def fund(row, after_sale, event_time, amount=-1000):
            return {
                "sourceRecordId": row,
                "recordType": "fund",
                "rowNumber": row,
                "primaryIdentifier": "FUN{}".format(row),
                "secondaryIdentifier": "SUB1",
                "eventTime": event_time,
                "amountCents": amount,
                "rawValuesJson": {
                    "动账场景": "退款-结算后退款-退用户",
                    "动账方向": "出账",
                    "售后编号": after_sale,
                },
            }

        def after_sale(after_sale_id="AFTER1", status="退款成功"):
            return {
                "sourceRecordId": 30,
                "recordType": "after_sale",
                "rowNumber": 3,
                "primaryIdentifier": after_sale_id,
                "secondaryIdentifier": "SUB1",
                "amountCents": 1000,
                "rawValuesJson": {"售后单号": after_sale_id, "商品单号": "SUB1", "售后状态": status},
            }

        within = calculate_refund_settlement_reconciliation(
            [settlement(), fund(4, "AFTER1", "2023-12-01T10:04:59"), after_sale()], 1, 300, 86400
        )
        self.assertEqual(within["results"][0]["status"], "matched")

        closed = calculate_refund_settlement_reconciliation(
            [settlement(), fund(4, "AFTER1", "2023-12-01T10:04:59"), after_sale(status="售后关闭")],
            1, 300, 86400,
        )
        self.assertEqual(closed["results"][0]["status"], "not_calculable")
        self.assertIn("不能作为已成功退款", closed["results"][0]["explanation"])

        candidate = calculate_refund_settlement_reconciliation(
            [settlement(), fund(4, "AFTER1", "2023-12-01T10:05:01")], 1, 300, 86400
        )
        self.assertEqual(candidate["results"][0]["status"], "outside_auto_window")
        self.assertEqual(candidate["results"][0]["matchedCandidateCount"], 1)

        excluded = calculate_refund_settlement_reconciliation(
            [settlement(), fund(4, "AFTER1", "2023-12-02T10:00:01")], 1, 300, 86400
        )
        self.assertEqual(excluded["results"][0]["status"], "missing_fund")
        self.assertEqual(excluded["results"][0]["candidateCount"], 0)

        multiple = calculate_refund_settlement_reconciliation(
            [
                settlement(),
                fund(4, "AFTER1", "2023-12-01T10:00:01"),
                fund(5, "AFTER2", "2023-12-01T10:00:02"),
            ],
            1,
            300,
            86400,
        )
        self.assertEqual(multiple["results"][0]["status"], "multiple_candidates")
        self.assertEqual(multiple["results"][0]["matchedCandidateCount"], 2)

    def test_ordinary_account_mismatch_stops_auto_match_and_long_gap_is_warning(self):
        settlement = {
            "recordType": "settlement", "rowNumber": 3, "primaryIdentifier": "SUB1",
            "eventTime": "2023-12-01T10:00:00", "amountCents": 1000,
            "rawValuesJson": {"结算单类型": "已结算", "结算账户": "聚合账户"},
        }
        fund = {
            "sourceRecordId": 4, "recordType": "fund", "rowNumber": 4,
            "primaryIdentifier": "FUN1", "secondaryIdentifier": "SUB1",
            "eventTime": "2023-12-03T10:00:01", "amountCents": 1000,
            "rawValuesJson": {
                "动账场景": "货款结算入账", "动账方向": "入账", "动账账户": "其他账户",
            },
        }
        mismatch = calculate_ordinary_settlement_reconciliation([settlement, fund], 1)
        self.assertEqual(mismatch["results"][0]["status"], "not_calculable")
        self.assertIn("账户不一致", mismatch["results"][0]["explanation"])

        fund["rawValuesJson"]["动账账户"] = "聚合账户"
        warning = calculate_ordinary_settlement_reconciliation([settlement, fund], 1)
        self.assertEqual(warning["results"][0]["status"], "matched")
        self.assertTrue(warning["results"][0]["timeAnomaly"])
        self.assertIn("超过24小时", warning["results"][0]["explanation"])


if __name__ == "__main__":
    unittest.main()
