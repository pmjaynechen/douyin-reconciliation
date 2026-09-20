import json
import re
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import __version__
from .export_xlsx import XLSX_MIME_TYPE
from .services import (
    DuplicateFileError,
    DuplicateTaskError,
    NotFoundError,
    ValidationError,
)


class ApiApplication:
    def __init__(self, service):
        self.service = service

    def handle(self, method, path, body=b"", headers=None):
        headers = headers or {}
        parsed_url = urlparse(path)
        route_path = parsed_url.path
        query = parse_qs(parsed_url.query)
        try:
            if method == "GET" and route_path == "/api/health":
                result = self.service.health()
                result["version"] = __version__
                return json_response(200, result)
            if method == "GET" and route_path == "/api/tasks":
                return json_response(200, {"tasks": self.service.list_tasks()})
            if method == "GET" and route_path == "/api/settings":
                return json_response(200, {"currentRule": self.service.current_rule()})
            if method == "GET" and route_path == "/api/configuration":
                return json_response(200, self.service.configuration_center())
            if method == "GET" and route_path == "/api/master-data/options":
                return json_response(200, self.service.master_data_options())
            if method == "POST" and route_path == "/api/configuration/entities":
                return json_response(
                    201, self.service.create_business_entity(parse_json(body))
                )
            if method == "POST" and route_path == "/api/configuration/stores":
                return json_response(
                    201, self.service.create_platform_store(parse_json(body))
                )
            store_status_match = re.fullmatch(
                r"/api/configuration/stores/([^/]+)/status", route_path
            )
            if method == "POST" and store_status_match:
                return json_response(
                    200,
                    self.service.update_platform_store_status(
                        store_status_match.group(1), parse_json(body)
                    ),
                )
            if method == "POST" and route_path == "/api/configuration/value-mappings":
                return json_response(
                    201, self.service.create_platform_value_mapping(parse_json(body))
                )
            if method == "POST" and route_path == "/api/configuration/rules/drafts":
                return json_response(
                    201, {"rule": self.service.create_rule_draft()}
                )
            rule_test_match = re.fullmatch(
                r"/api/configuration/rules/([^/]+)/test", route_path
            )
            if method == "POST" and rule_test_match:
                return json_response(
                    200, self.service.test_rule_draft(rule_test_match.group(1))
                )
            rule_activate_match = re.fullmatch(
                r"/api/configuration/rules/([^/]+)/activate", route_path
            )
            if method == "POST" and rule_activate_match:
                return json_response(
                    200,
                    self.service.activate_rule_draft(
                        rule_activate_match.group(1), parse_json(body)
                    ),
                )
            rule_update_match = re.fullmatch(
                r"/api/configuration/rules/([^/]+)", route_path
            )
            if method == "POST" and rule_update_match:
                return json_response(
                    200,
                    {"rule": self.service.update_rule_draft(
                        rule_update_match.group(1), parse_json(body)
                    )},
                )
            if method == "POST" and route_path == "/api/configuration/templates/drafts":
                return json_response(201, {"template": self.service.create_bill_template_draft()})
            template_test_match = re.fullmatch(
                r"/api/configuration/templates/([^/]+)/test", route_path
            )
            if method == "POST" and template_test_match:
                original_name = unquote(headers.get("X-File-Name", ""))
                return json_response(
                    200,
                    self.service.test_bill_template(
                        template_test_match.group(1), original_name, body
                    ),
                )
            template_activate_match = re.fullmatch(
                r"/api/configuration/templates/([^/]+)/activate", route_path
            )
            if method == "POST" and template_activate_match:
                return json_response(
                    200,
                    self.service.activate_bill_template(
                        template_activate_match.group(1), parse_json(body)
                    ),
                )
            template_update_match = re.fullmatch(
                r"/api/configuration/templates/([^/]+)", route_path
            )
            if method == "POST" and template_update_match:
                return json_response(
                    200,
                    {"template": self.service.update_bill_template_draft(
                        template_update_match.group(1), parse_json(body)
                    )},
                )
            if method == "POST" and route_path == "/api/sample/load":
                result = self.service.load_sample()
                return json_response(201 if result["created"] else 200, result)
            if method == "POST" and route_path == "/api/tasks":
                payload = parse_json(body)
                return json_response(201, {"task": self.service.create_task(payload)})
            task_period_match = re.fullmatch(
                r"/api/tasks/([^/]+)/correct-period", route_path
            )
            if method == "POST" and task_period_match:
                payload = parse_json(body)
                return json_response(
                    201,
                    self.service.correct_task_period(
                        task_period_match.group(1), payload
                    ),
                )
            task_completion_match = re.fullmatch(
                r"/api/tasks/([^/]+)/completion", route_path
            )
            if method == "GET" and task_completion_match:
                return json_response(
                    200,
                    self.service.get_completion_summary(
                        task_completion_match.group(1)
                    ),
                )
            operating_report_match = re.fullmatch(
                r"/api/tasks/([^/]+)/operating-report-readiness", route_path
            )
            if method == "GET" and operating_report_match:
                return json_response(
                    200,
                    self.service.get_operating_report_readiness(
                        operating_report_match.group(1)
                    ),
                )
            operating_evidence_match = re.fullmatch(
                r"/api/tasks/([^/]+)/operating-evidence", route_path
            )
            if method == "GET" and operating_evidence_match:
                return json_response(
                    200,
                    self.service.get_operating_evidence(
                        operating_evidence_match.group(1)
                    ),
                )
            operating_evidence_results_match = re.fullmatch(
                r"/api/tasks/([^/]+)/operating-evidence/([^/]+)/results", route_path
            )
            if method == "GET" and operating_evidence_results_match:
                return json_response(
                    200,
                    self.service.get_operating_evidence_results(
                        operating_evidence_results_match.group(1),
                        operating_evidence_results_match.group(2),
                        _first_query(query, "status", "all"),
                        _first_query(query, "page", 1),
                        _first_query(query, "pageSize", 50),
                    ),
                )
            operating_evidence_file_match = re.fullmatch(
                r"/api/tasks/([^/]+)/operating-evidence/([^/]+)/files", route_path
            )
            if method == "POST" and operating_evidence_file_match:
                original_name = unquote(headers.get("X-File-Name", ""))
                replacement_reason = unquote(headers.get("X-Replacement-Reason", ""))
                return json_response(
                    201,
                    self.service.upload_operating_evidence_file(
                        operating_evidence_file_match.group(1),
                        operating_evidence_file_match.group(2),
                        original_name,
                        body,
                        replacement_reason,
                    ),
                )
            task_complete_match = re.fullmatch(
                r"/api/tasks/([^/]+)/complete", route_path
            )
            if method == "POST" and task_complete_match:
                return json_response(
                    200,
                    self.service.complete_task(
                        task_complete_match.group(1), parse_json(body)
                    ),
                )
            task_reopen_match = re.fullmatch(
                r"/api/tasks/([^/]+)/reopen", route_path
            )
            if method == "POST" and task_reopen_match:
                return json_response(
                    200,
                    self.service.reopen_task(
                        task_reopen_match.group(1), parse_json(body)
                    ),
                )
            platform_balance_results_match = re.fullmatch(
                r"/api/tasks/([^/]+)/platform-balance-results", route_path
            )
            if method == "GET" and platform_balance_results_match:
                return json_response(
                    200,
                    self.service.get_platform_balance_results(
                        platform_balance_results_match.group(1),
                        _first_query(query, "status", "all"),
                        _first_query(query, "page", "1"),
                        _first_query(query, "pageSize", "50"),
                    ),
                )
            platform_balance_file_match = re.fullmatch(
                r"/api/tasks/([^/]+)/platform-balance-files", route_path
            )
            if method == "POST" and platform_balance_file_match:
                original_name = unquote(headers.get("X-File-Name", ""))
                replacement_reason = unquote(headers.get("X-Replacement-Reason", ""))
                return json_response(
                    201,
                    self.service.upload_platform_balance_workbook(
                        platform_balance_file_match.group(1),
                        original_name,
                        body,
                        replacement_reason,
                    ),
                )
            pending_settlement_results_match = re.fullmatch(
                r"/api/tasks/([^/]+)/pending-settlement-results", route_path
            )
            if method == "GET" and pending_settlement_results_match:
                return json_response(
                    200,
                    self.service.get_pending_settlement_results(
                        pending_settlement_results_match.group(1),
                        _first_query(query, "status", "all"),
                        _first_query(query, "page", "1"),
                        _first_query(query, "pageSize", "50"),
                    ),
                )
            pending_settlement_file_match = re.fullmatch(
                r"/api/tasks/([^/]+)/pending-settlement-files", route_path
            )
            if method == "POST" and pending_settlement_file_match:
                original_name = unquote(headers.get("X-File-Name", ""))
                replacement_reason = unquote(headers.get("X-Replacement-Reason", ""))
                return json_response(
                    201,
                    self.service.upload_pending_settlement_workbook(
                        pending_settlement_file_match.group(1),
                        original_name,
                        body,
                        replacement_reason,
                    ),
                )
            manual_resolution_match = re.fullmatch(
                r"/api/tasks/([^/]+)/files/([^/]+)/results/([^/]+)/([^/]+)/manual-resolution",
                route_path,
            )
            if method == "POST" and manual_resolution_match:
                return json_response(
                    200,
                    self.service.save_manual_resolution(
                        manual_resolution_match.group(1),
                        manual_resolution_match.group(2),
                        manual_resolution_match.group(3),
                        manual_resolution_match.group(4),
                        parse_json(body),
                    ),
                )
            task_match = re.fullmatch(r"/api/tasks/([^/]+)", route_path)
            if method == "GET" and task_match:
                return json_response(200, self.service.get_task(task_match.group(1)))
            record_match = re.fullmatch(
                r"/api/tasks/([^/]+)/files/([^/]+)/records", route_path
            )
            if method == "GET" and record_match:
                return json_response(
                    200,
                    self.service.get_import_records(
                        record_match.group(1),
                        record_match.group(2),
                        _first_query(query, "sheet"),
                        _first_query(query, "page", "1"),
                        _first_query(query, "pageSize", "50"),
                    ),
                )
            wide_reconciliation_match = re.fullmatch(
                r"/api/tasks/([^/]+)/files/([^/]+)/wide-reconciliation-results",
                route_path,
            )
            if method == "GET" and wide_reconciliation_match:
                return json_response(
                    200,
                    self.service.get_wide_reconciliation_results(
                        wide_reconciliation_match.group(1),
                        wide_reconciliation_match.group(2),
                        _first_query(query, "status", "all"),
                        _first_query(query, "scene", "all"),
                        _first_query(query, "query", ""),
                        _first_query(query, "page", "1"),
                        _first_query(query, "pageSize", "50"),
                    ),
                )
            reconciliation_detail_match = re.fullmatch(
                r"/api/tasks/([^/]+)/files/([^/]+)/reconciliation-results/([^/]+)",
                route_path,
            )
            if method == "GET" and reconciliation_detail_match:
                return json_response(
                    200,
                    self.service.get_reconciliation_result(
                        reconciliation_detail_match.group(1),
                        reconciliation_detail_match.group(2),
                        reconciliation_detail_match.group(3),
                    ),
                )
            reconciliation_match = re.fullmatch(
                r"/api/tasks/([^/]+)/files/([^/]+)/reconciliation-results",
                route_path,
            )
            if method == "GET" and reconciliation_match:
                return json_response(
                    200,
                    self.service.get_reconciliation_results(
                        reconciliation_match.group(1),
                        reconciliation_match.group(2),
                        _first_query(query, "status", "all"),
                        _first_query(query, "page", "1"),
                        _first_query(query, "pageSize", "50"),
                    ),
                )
            refund_reconciliation_detail_match = re.fullmatch(
                r"/api/tasks/([^/]+)/files/([^/]+)/refund-reconciliation-results/([^/]+)",
                route_path,
            )
            if method == "GET" and refund_reconciliation_detail_match:
                return json_response(
                    200,
                    self.service.get_refund_reconciliation_result(
                        refund_reconciliation_detail_match.group(1),
                        refund_reconciliation_detail_match.group(2),
                        refund_reconciliation_detail_match.group(3),
                    ),
                )
            refund_reconciliation_match = re.fullmatch(
                r"/api/tasks/([^/]+)/files/([^/]+)/refund-reconciliation-results",
                route_path,
            )
            if method == "GET" and refund_reconciliation_match:
                return json_response(
                    200,
                    self.service.get_refund_reconciliation_results(
                        refund_reconciliation_match.group(1),
                        refund_reconciliation_match.group(2),
                        _first_query(query, "status", "all"),
                        _first_query(query, "page", "1"),
                        _first_query(query, "pageSize", "50"),
                    ),
                )
            export_match = re.fullmatch(
                r"/api/tasks/([^/]+)/files/([^/]+)/exports/([^/]+)\.xlsx",
                route_path,
            )
            if method == "GET" and export_match:
                exported = self.service.export_results(
                    export_match.group(1),
                    export_match.group(2),
                    export_match.group(3),
                    _first_query(query, "status", "all"),
                    _first_query(query, "scene", "all"),
                    _first_query(query, "query", ""),
                )
                return (
                    200,
                    {
                        "Content-Type": XLSX_MIME_TYPE,
                        "Content-Disposition": (
                            "attachment; filename=reconciliation.xlsx; filename*=UTF-8''{}"
                        ).format(quote(exported["fileName"])),
                        "Cache-Control": "no-store",
                    },
                    exported["content"],
                )
            supplementary_detail_match = re.fullmatch(
                r"/api/tasks/([^/]+)/files/([^/]+)/supplementary-results/([^/]+)/([^/]+)",
                route_path,
            )
            if method == "GET" and supplementary_detail_match:
                return json_response(
                    200,
                    self.service.get_supplementary_result(
                        supplementary_detail_match.group(1),
                        supplementary_detail_match.group(2),
                        supplementary_detail_match.group(3),
                        supplementary_detail_match.group(4),
                    ),
                )
            supplementary_match = re.fullmatch(
                r"/api/tasks/([^/]+)/files/([^/]+)/supplementary-results/([^/]+)",
                route_path,
            )
            if method == "GET" and supplementary_match:
                return json_response(
                    200,
                    self.service.get_supplementary_results(
                        supplementary_match.group(1),
                        supplementary_match.group(2),
                        supplementary_match.group(3),
                        _first_query(query, "status", "all"),
                        _first_query(query, "page", "1"),
                        _first_query(query, "pageSize", "50"),
                    ),
                )
            file_match = re.fullmatch(r"/api/tasks/([^/]+)/files", route_path)
            if method == "POST" and file_match:
                original_name = unquote(headers.get("X-File-Name", ""))
                replacement_reason = unquote(headers.get("X-Replacement-Reason", ""))
                return json_response(
                    201,
                    self.service.upload_workbook(
                        file_match.group(1), original_name, body, replacement_reason
                    ),
                )
            return json_response(404, {"error": "没有找到这个接口"})
        except ValidationError as exc:
            return json_response(400, {"error": str(exc)})
        except DuplicateTaskError as exc:
            return json_response(
                409,
                {"error": str(exc), "existingTask": exc.task},
            )
        except DuplicateFileError as exc:
            return json_response(
                409,
                {"error": str(exc), "existingFile": exc.file_version},
            )
        except NotFoundError as exc:
            return json_response(404, {"error": str(exc)})
        except json.JSONDecodeError:
            return json_response(400, {"error": "请求内容不是有效JSON"})
        except Exception:
            return json_response(500, {"error": "系统处理失败，请查看本机日志"})


def parse_json(body):
    if not body:
        raise json.JSONDecodeError("empty", "", 0)
    return json.loads(body.decode("utf-8"))


def _first_query(query, key, default=None):
    values = query.get(key)
    return values[0] if values else default


def json_response(status, payload):
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return status, {"Content-Type": "application/json; charset=utf-8"}, encoded
