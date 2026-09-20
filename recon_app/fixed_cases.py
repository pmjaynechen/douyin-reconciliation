import re
import sys
import threading
import time
import unittest
from pathlib import Path


CASE_LABELS = {
    "C01": "2,435行订单金额全部通过",
    "C02": "381行结算四项金额全部通过",
    "C03": "375条普通结算唯一命中",
    "C04": "6条退款结算净额一致",
    "C05": "114条缺历史订单不误报少结",
    "C06": "14个多次售后订单完整保留",
    "C07": "28条售后关闭不当作退款",
    "C08": "缺货号订单不计算成本",
    "C09": "重复流水号阻止自动判断",
    "C10": "两组退款候选不自动选择",
    "C11": "新费用等待用户分类",
    "C12": "提现不显示银行已到账",
    "C13": "金额差额等于容差仍可核对一致",
    "C14": "金额差额超过容差进入不一致",
    "C15": "退款在自动归组窗口内可归组",
    "C16": "退款超过自动归组窗口只列候选",
    "C17": "结算等待边界前等待，超过后提示核实",
    "C18": "售后未结束优先等待售后",
    "C19": "订单应收与结算收入不符必须处理",
    "C20": "超期已完成订单未结算必须处理",
    "C21": "结算与资金账户不一致不自动通过",
    "C22": "售后关闭不能被退款净额覆盖",
    "C23": "订单文件混入多个月份阻止导入",
}

DEFAULT_RULE_PARAMETERS = {
    "tolerance_cents": 1,
    "refund_auto_group_seconds": 300,
    "refund_candidate_seconds": 86400,
    "settlement_wait_days": 7,
}

_FIXED_CASE_LOCK = threading.Lock()


class _FixedCaseResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.case_results = {}

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "passed", None)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failed", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "failed", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "failed", "案例被跳过：{}".format(reason))

    def _record(self, test, status, message):
        match = re.search(r"\.test_(c\d{2})_", test.id(), re.IGNORECASE)
        if match is None:
            return
        case_id = match.group(1).upper()
        self.case_results[case_id] = {
            "caseId": case_id,
            "label": CASE_LABELS.get(case_id, case_id),
            "status": status,
            "message": _clean_message(message),
        }


def run_fixed_cases(base_dir=None, parameters=None):
    base_dir = Path(base_dir or Path(__file__).resolve().parent.parent)
    tests_dir = base_dir / "tests"
    if not tests_dir.is_dir():
        raise RuntimeError("没有找到固定案例测试目录：{}".format(tests_dir))

    selected_parameters = dict(DEFAULT_RULE_PARAMETERS)
    selected_parameters.update(parameters or {})
    original_path = list(sys.path)
    previous_parameters = {}
    started_at = time.perf_counter()
    with _FIXED_CASE_LOCK:
        try:
            sys.path.insert(0, str(tests_dir))
            suite = unittest.defaultTestLoader.discover(
                str(tests_dir), pattern="test_fixed_cases.py", top_level_dir=str(tests_dir)
            )
            test_classes = {test.__class__ for test in _iter_tests(suite)}
            previous_parameters = {
                test_class: getattr(test_class, "rule_parameters", None)
                for test_class in test_classes
            }
            for test_class in test_classes:
                test_class.rule_parameters = dict(selected_parameters)
            result = _FixedCaseResult()
            suite.run(result)
        finally:
            for test_class, previous in previous_parameters.items():
                if previous is None:
                    delattr(test_class, "rule_parameters")
                else:
                    test_class.rule_parameters = previous
            sys.path[:] = original_path

    ordered = []
    for case_id, label in CASE_LABELS.items():
        ordered.append(
            result.case_results.get(
                case_id,
                {
                    "caseId": case_id,
                    "label": label,
                    "status": "failed",
                    "message": "案例没有执行，请检查测试文件是否完整。",
                },
            )
        )
    passed_count = sum(1 for item in ordered if item["status"] == "passed")
    return {
        "status": "passed" if passed_count == len(CASE_LABELS) else "failed",
        "totalCount": len(CASE_LABELS),
        "passedCount": passed_count,
        "failedCount": len(CASE_LABELS) - passed_count,
        "durationSeconds": round(time.perf_counter() - started_at, 3),
        "parameters": {
            "toleranceCents": selected_parameters["tolerance_cents"],
            "refundAutoGroupSeconds": selected_parameters["refund_auto_group_seconds"],
            "refundCandidateSeconds": selected_parameters["refund_candidate_seconds"],
            "settlementWaitDays": selected_parameters["settlement_wait_days"],
        },
        "caseResults": ordered,
    }


def _iter_tests(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_tests(item)
        else:
            yield item


def _clean_message(message):
    if not message:
        return None
    lines = [line.strip() for line in str(message).splitlines() if line.strip()]
    return lines[-1][:1000] if lines else None
