import json
import unittest
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from recon_app.refund_reconciliation import calculate_refund_settlement_reconciliation


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "refund_component_golden_triangle.json"
REQUIRED_COVERAGE = {
    "full_refund",
    "partial_refund",
    "component_mismatch",
    "platform_subsidy_missing",
    "platform_subsidy_short",
    "platform_subsidy_excess",
    "no_platform_subsidy",
    "influencer_subsidy_only",
    "other_subsidy_only",
    "one_cent_boundary",
    "two_cents_fail",
    "missing_after_sale",
    "missing_fund",
}


class RefundComponentFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_fixture_is_explicitly_simulated_and_covers_required_cases(self):
        meta = self.fixture["meta"]
        self.assertEqual(meta["dataClassification"], "模拟测试数据")
        self.assertEqual(
            meta["warning"],
            "模拟，公式来自外部课程资料，尚待真实样本确认",
        )
        scenario_ids = [item["id"] for item in self.fixture["scenarios"]]
        self.assertEqual(len(scenario_ids), len(set(scenario_ids)))
        coverage = {
            tag
            for scenario in self.fixture["scenarios"]
            for tag in scenario["coverageTags"]
        }
        self.assertTrue(REQUIRED_COVERAGE.issubset(coverage))

    def test_expected_platform_subsidy_formula_and_component_results_are_consistent(self):
        tolerance = self.fixture["meta"]["toleranceCents"]
        for scenario in self.fixture["scenarios"]:
            with self.subTest(scenario=scenario["id"]):
                expected = scenario["expected"]
                after_sale = scenario["afterSale"]
                fund_rows = scenario["fundRows"]
                if after_sale is None:
                    self.assertIsNone(expected["expectedPlatformSubsidyClawbackCents"])
                    self.assertEqual(expected["compositionStatus"], "not_calculable")
                    continue
                if not fund_rows:
                    self.assertEqual(expected["currentNetStatus"], "missing_fund")
                    self.assertEqual(expected["compositionStatus"], "not_calculable")
                    continue

                original = scenario["originalSettlement"]
                ratio = Decimal(after_sale["userRefundCents"]) / Decimal(original["userPaidCents"])
                calculated_platform = int(
                    (Decimal(original["platformSubsidyCents"]) * ratio).quantize(
                        Decimal("1"), rounding=ROUND_HALF_UP
                    )
                )
                actual_platform = sum(
                    abs(row["signedAmountCents"])
                    for row in fund_rows
                    if row["component"] == "platform_subsidy_clawback"
                )
                actual_user_refund = sum(
                    abs(row["signedAmountCents"])
                    for row in fund_rows
                    if row["component"] == "user_refund"
                )
                difference = actual_platform - calculated_platform

                self.assertEqual(
                    expected["expectedPlatformSubsidyClawbackCents"], calculated_platform
                )
                self.assertEqual(expected["actualPlatformSubsidyClawbackCents"], actual_platform)
                self.assertEqual(expected["platformSubsidyDifferenceCents"], difference)

                expected_platform_status = "passed"
                if abs(difference) > tolerance:
                    if actual_platform == 0 and calculated_platform > 0:
                        expected_platform_status = "missing"
                    elif difference < 0:
                        expected_platform_status = "short"
                    else:
                        expected_platform_status = "excess"
                self.assertEqual(expected["platformSubsidyStatus"], expected_platform_status)

                expected_user_status = (
                    "passed"
                    if abs(actual_user_refund - after_sale["userRefundCents"]) <= tolerance
                    else "mismatch"
                )
                self.assertEqual(expected["userRefundStatus"], expected_user_status)

                has_unconfirmed_subsidy = any(
                    row["component"]
                    in ("influencer_subsidy_clawback", "other_subsidy_clawback")
                    for row in fund_rows
                )
                if has_unconfirmed_subsidy:
                    expected_composition_status = "needs_separate_rule"
                elif expected_platform_status == "passed" and expected_user_status == "passed":
                    expected_composition_status = "passed"
                else:
                    expected_composition_status = "failed"
                self.assertEqual(expected["compositionStatus"], expected_composition_status)

    def test_current_net_reconciliation_matches_fixture_expectations(self):
        for index, scenario in enumerate(self.fixture["scenarios"], 1):
            with self.subTest(scenario=scenario["id"]):
                records = [
                    {
                        "recordType": "settlement",
                        "rowNumber": 3,
                        "primaryIdentifier": scenario["subOrderId"],
                        "eventTime": "2026-01-01T10:00:00",
                        "amountCents": scenario["refundSettlementAmountCents"],
                        "rawValuesJson": {"结算单类型": "结算后退款-模拟测试"},
                    }
                ]
                for offset, row in enumerate(scenario["fundRows"], 1):
                    records.append(
                        {
                            "sourceRecordId": index * 100 + offset,
                            "recordType": "fund",
                            "rowNumber": 3 + offset,
                            "primaryIdentifier": row["transactionId"],
                            "secondaryIdentifier": scenario["subOrderId"],
                            "eventTime": "2026-01-01T10:00:{:02d}".format(offset),
                            "amountCents": row["signedAmountCents"],
                            "rawValuesJson": {
                                "动账场景": row["scene"],
                                "动账方向": row["direction"],
                                "售后编号": row["afterSaleId"],
                            },
                        }
                    )
                if scenario["afterSale"] is not None:
                    after_sale = scenario["afterSale"]
                    records.append({
                        "sourceRecordId": index * 100 + 90,
                        "recordType": "after_sale",
                        "rowNumber": 90,
                        "primaryIdentifier": after_sale["afterSaleId"],
                        "secondaryIdentifier": scenario["subOrderId"],
                        "amountCents": after_sale["userRefundCents"],
                        "rawValuesJson": {
                            "售后单号": after_sale["afterSaleId"],
                            "商品单号": scenario["subOrderId"],
                            "售后状态": after_sale["status"],
                        },
                    })

                result = calculate_refund_settlement_reconciliation(
                    records,
                    self.fixture["meta"]["toleranceCents"],
                    300,
                    86400,
                )["results"][0]
                expected_status = (
                    "not_calculable"
                    if scenario["afterSale"] is None
                    and scenario["expected"]["currentNetStatus"] == "matched"
                    else scenario["expected"]["currentNetStatus"]
                )
                self.assertEqual(result["status"], expected_status)
                self.assertEqual(
                    result["fundNetAmountCents"],
                    scenario["expected"]["currentNetAmountCents"],
                )
                self.assertEqual(
                    result["differenceCents"],
                    scenario["expected"]["currentNetDifferenceCents"],
                )

    def test_component_trial_detects_net_consistent_composition_errors(self):
        expected_statuses = {
            "passed": "matched",
            "failed": "mismatch",
            "needs_separate_rule": "limited",
            "not_calculable": "missing_evidence",
        }
        for index, scenario in enumerate(self.fixture["scenarios"], 1):
            with self.subTest(scenario=scenario["id"]):
                result = calculate_refund_settlement_reconciliation(
                    _build_component_records(scenario, index),
                    self.fixture["meta"]["toleranceCents"],
                    300,
                    86400,
                )["results"][0]
                self.assertEqual(
                    result["componentStatus"],
                    expected_statuses[scenario["expected"]["compositionStatus"]],
                )
                self.assertTrue(result["componentCheck"]["isTrial"])
                self.assertIn("外部课程资料", result["componentCheck"]["ruleSource"])


def _build_component_records(scenario, index):
    original = scenario["originalSettlement"]
    actual_platform = sum(
        abs(row["signedAmountCents"])
        for row in scenario["fundRows"]
        if row["component"] == "platform_subsidy_clawback"
    )
    actual_user = sum(
        abs(row["signedAmountCents"])
        for row in scenario["fundRows"]
        if row["component"] == "user_refund"
    )
    records = [
        {
            "recordType": "settlement",
            "rowNumber": 2,
            "primaryIdentifier": scenario["subOrderId"],
            "eventTime": "2026-01-01T09:00:00",
            "amountCents": original["userPaidCents"] + original["platformSubsidyCents"],
            "rawValuesJson": {
                "结算单类型": "已结算",
                "用户实付": _yuan(original["userPaidCents"]),
                "平台补贴": _yuan(original["platformSubsidyCents"]),
                "达人补贴": _yuan(original["influencerSubsidyCents"]),
                "抖音支付补贴": "0.00",
                "抖音月付营销补贴": _yuan(original["otherSubsidyCents"]),
            },
        },
        {
            "recordType": "settlement",
            "rowNumber": 3,
            "primaryIdentifier": scenario["subOrderId"],
            "eventTime": "2026-01-01T10:00:00",
            "amountCents": scenario["refundSettlementAmountCents"],
            "rawValuesJson": {
                "结算单类型": "结算后退款-模拟测试",
                "用户实付": _yuan(-actual_user),
                "平台补贴": _yuan(-actual_platform),
            },
        },
    ]
    if scenario["afterSale"] is not None:
        after_sale = scenario["afterSale"]
        records.append(
            {
                "recordType": "after_sale",
                "rowNumber": 4,
                "primaryIdentifier": after_sale["afterSaleId"],
                "secondaryIdentifier": scenario["subOrderId"],
                "eventTime": "2026-01-01T09:30:00",
                "amountCents": after_sale["userRefundCents"],
                "rawValuesJson": {
                    "售后单号": after_sale["afterSaleId"],
                    "商品单号": scenario["subOrderId"],
                    "售后状态": after_sale["status"],
                    "退商品金额（元）": _yuan(after_sale["userRefundCents"]),
                    "退运费金额（元）": "0.00",
                },
            }
        )
    for offset, row in enumerate(scenario["fundRows"], 1):
        raw = {
            "动账场景": row["scene"],
            "动账方向": row["direction"],
            "售后编号": row["afterSaleId"],
            "订单退款": "0.00",
            "实际平台补贴": "0.00",
            "实际达人补贴": "0.00",
            "实际抖音支付补贴": "0.00",
            "实际抖音月付营销补贴": "0.00",
        }
        field_by_component = {
            "user_refund": "订单退款",
            "platform_subsidy_clawback": "实际平台补贴",
            "influencer_subsidy_clawback": "实际达人补贴",
            "other_subsidy_clawback": "实际抖音月付营销补贴",
        }
        raw[field_by_component[row["component"]]] = _yuan(row["signedAmountCents"])
        records.append(
            {
                "sourceRecordId": index * 100 + offset,
                "recordType": "fund",
                "rowNumber": 4 + offset,
                "primaryIdentifier": row["transactionId"],
                "secondaryIdentifier": scenario["subOrderId"],
                "eventTime": "2026-01-01T10:00:{:02d}".format(offset),
                "amountCents": row["signedAmountCents"],
                "rawValuesJson": raw,
            }
        )
    return records


def _yuan(cents):
    return "{:.2f}".format(Decimal(cents) / Decimal(100))


if __name__ == "__main__":
    unittest.main()
