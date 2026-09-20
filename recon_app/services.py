import hashlib
import json
import os
import re
import sqlite3
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from .amount_checks import calculate_amount_checks
from .configuration_catalog import (
    BASE_DATA_CATALOG,
    DEFAULT_TEMPLATE_ID,
    RULE_CATALOG,
    VALUE_MAPPING_TYPES,
)
from .data_import import analyze_workbook_data, normalize_identifier, parse_money_or_number
from .database import append_operation, connect, row_to_dict, utc_now
from .fixed_cases import run_fixed_cases
from .platform_balance import (
    MAPPING_VERSION as PLATFORM_BALANCE_MAPPING_VERSION,
    calculate_platform_balance,
    inspect_platform_balance_workbook,
)
from .pending_settlement import (
    ATTENTION_STATUSES as PENDING_SETTLEMENT_ATTENTION_STATUSES,
    MAPPING_VERSION as PENDING_SETTLEMENT_MAPPING_VERSION,
    calculate_pending_settlement,
    inspect_pending_settlement_workbook,
)
from .operating_evidence import calculate_simulated_operating_evidence
from .record_views import SHEET_VIEWS, build_record_page, enrich_import_summary
from .refund_reconciliation import calculate_refund_settlement_reconciliation
from .result_exports import (
    RESULT_TYPE_LABELS,
    build_result_export,
    build_wide_reconciliation_export,
)
from .settlement_reconciliation import calculate_ordinary_settlement_reconciliation
from .supplementary_reconciliation import calculate_supplementary_reconciliation
from .wide_reconciliation import build_wide_reconciliation_page
from .xlsx import WorkbookInspectionError, inspect_workbook


MAX_WORKBOOK_BYTES = 50 * 1024 * 1024
MAX_WIDE_EXPORT_ROWS = 100000

OPERATING_EVIDENCE_TYPES = {
    "erp_cost": {
        "taskId": "M020",
        "label": "ERP历史成本与退货入库",
        "shortLabel": "ERP成本",
        "unlock": "核对历史出库成本、退货入库和成本冲回",
        "guidance": "优先提供订单或子订单、SKU、出库数量、单位成本、出库日期，以及退货入库数量和日期。",
    },
    "fulfillment_expense": {
        "taskId": "M021",
        "label": "快递与仓储费用",
        "shortLabel": "履约费用",
        "unlock": "核对运单、重量、地区、计价和仓储费用",
        "guidance": "优先提供运单号、发货日期、重量、收件地区、计费项目、账单金额和补收/退款标识。",
    },
    "operating_expense": {
        "taskId": "M022-B",
        "label": "投流、线下及管理费用",
        "shortLabel": "经营费用",
        "unlock": "补齐可归属店铺的经营费用和分摊依据",
        "guidance": "优先提供发生日期、费用类别、金额、归属店铺、原始单号、分摊方式和说明。",
    },
}

SUPPLEMENTARY_RESULT_TYPES = {
    "cross_month": {
        "summaryKey": "crossMonth",
        "attention": {
            "missing_historical_order", "missing_order_data", "multiple_history_orders",
            "settlement_receivable_mismatch", "settlement_receivable_not_calculable",
            "settlement_before_refund_review", "possibly_unsettled", "not_calculable",
            "order_status_requires_review",
        },
    },
    "after_sale": {
        "summaryKey": "afterSales",
        "attention": {
            "new_after_sale_status", "after_sale_refund_conflict",
            "refund_missing_after_sale",
        },
    },
    "cost": {
        "summaryKey": "costs",
        "attention": {"missing_sku", "missing_cost", "multiple_cost_candidates", "not_calculable"},
    },
    "other_fund": {
        "summaryKey": "otherFunds",
        "attention": {"waiting_classification"},
    },
}

MANUAL_RESULT_TYPES = {
    "ordinary_settlement",
    "refund_settlement",
    "cross_month",
    "after_sale",
    "cost",
    "other_fund",
}

MANUAL_ACTION_TYPES = {
    "confirm",
    "select_candidate",
    "adjust_amount",
    "carry_forward",
}


class ValidationError(Exception):
    pass


class DuplicateTaskError(Exception):
    def __init__(self, task):
        super().__init__("同一主体、店铺和月份已经存在任务")
        self.task = task


class DuplicateFileError(Exception):
    def __init__(self, file_version):
        super().__init__("这个文件已经导入过，本次没有重复保存")
        self.file_version = file_version


class NotFoundError(Exception):
    pass


def clean_text(value, field_name, max_length=100):
    if not isinstance(value, str):
        raise ValidationError("{}不能为空".format(field_name))
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        raise ValidationError("{}不能为空".format(field_name))
    if len(cleaned) > max_length:
        raise ValidationError("{}不能超过{}个字符".format(field_name, max_length))
    return cleaned


def validate_period(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
        raise ValidationError("月份必须使用YYYY-MM格式")
    try:
        datetime.strptime(value, "%Y-%m")
    except ValueError:
        raise ValidationError("月份不是有效日期")
    return value


def _validate_wide_reconciliation_filters(status, scene, query):
    if status not in (
        "all", "needs_attention", "matched", "resolved", "no_settlement"
    ):
        raise ValidationError("宽表状态筛选条件不支持")
    if scene not in (
        "all", "ordinary_settlement", "refund_settlement", "cross_month",
        "after_sale", "cost", "other_fund", "order_only",
    ):
        raise ValidationError("宽表业务场景筛选条件不支持")
    if query is None:
        query = ""
    if not isinstance(query, str):
        raise ValidationError("搜索内容格式不正确")
    query = " ".join(query.strip().split())
    if len(query) > 100:
        raise ValidationError("搜索内容不能超过100个字符")
    return status, scene, query


class ReconciliationService:
    def __init__(self, database_path, upload_dir=None, sample_workbook_path=None):
        self.database_path = Path(database_path)
        self.upload_dir = Path(upload_dir or self.database_path.parent / "uploads")
        self.sample_workbook_path = Path(sample_workbook_path) if sample_workbook_path else None
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def health(self):
        with connect(self.database_path) as connection:
            connection.execute("SELECT 1").fetchone()
            migration = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
        return {"status": "ok", "database": "ok", "schemaVersion": migration["version"]}

    def current_rule(self):
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT id, version_label, tolerance_cents, refund_auto_group_seconds,
                       refund_candidate_seconds, settlement_wait_days, status, created_at
                FROM rule_versions
                WHERE status = 'current'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        rule = row_to_dict(row)
        if rule is None:
            raise RuntimeError("没有可用的规则版本")
        return _rule_to_api(rule)

    def configuration_center(self):
        with connect(self.database_path) as connection:
            templates = connection.execute(
                """
                SELECT * FROM bill_template_versions
                ORDER BY CASE status WHEN 'draft' THEN 0 WHEN 'current' THEN 1 ELSE 2 END,
                         created_at DESC
                """
            ).fetchall()
            current_rule = connection.execute(
                """
                SELECT id, version_label, tolerance_cents, refund_auto_group_seconds,
                       refund_candidate_seconds, settlement_wait_days, status,
                       notes, activated_at, fixed_case_summary_json, created_at
                FROM rule_versions
                WHERE status = 'current'
                ORDER BY created_at DESC LIMIT 1
                """
            ).fetchone()
            rule_draft = connection.execute(
                """
                SELECT * FROM rule_version_drafts
                ORDER BY created_at DESC LIMIT 1
                """
            ).fetchone()
            entity_store_rows = connection.execute(
                """
                SELECT e.id AS entity_id, e.name AS entity_name, e.status AS entity_status,
                       s.id AS store_id, s.name AS store_name, s.platform_code,
                       s.status AS store_status, s.created_at, s.updated_at,
                       COUNT(t.id) AS task_count, MAX(t.updated_at) AS last_used_at
                FROM business_entities e
                LEFT JOIN platform_stores s ON s.entity_id = e.id
                LEFT JOIN tasks t ON t.store_id = s.id AND t.is_sample = 0
                GROUP BY e.id, s.id
                ORDER BY CASE e.status WHEN 'active' THEN 0 ELSE 1 END,
                         e.name, CASE s.status WHEN 'active' THEN 0 ELSE 1 END, s.name
                """
            ).fetchall()
            mapping_rows = connection.execute(
                """
                SELECT * FROM platform_value_mappings
                ORDER BY mapping_type, source_value, version_number DESC
                """
            ).fetchall()
            unmapped_rows = connection.execute(
                """
                SELECT u.*, t.entity_name, t.store_name
                FROM unmapped_platform_values u
                LEFT JOIN tasks t ON t.id = u.latest_task_id
                WHERE u.status = 'pending'
                ORDER BY u.last_seen_at DESC, u.mapping_type, u.source_value
                """
            ).fetchall()
            template_payloads = [
                _bill_template_to_api(connection, row_to_dict(row))
                for row in templates
            ]
        current_template = next(
            (item for item in template_payloads if item["status"] == "current"), None
        )
        draft_template = next(
            (item for item in template_payloads if item["status"] == "draft"), None
        )
        base_data = [dict(item) for item in BASE_DATA_CATALOG]
        master_data = _master_data_to_api(entity_store_rows)
        for item in base_data:
            if item["code"] == "entity_store":
                item["items"] = [
                    {
                        "entityName": row["entity_name"],
                        "storeName": row["store_name"],
                        "taskCount": row["task_count"],
                        "lastUsedAt": row["last_used_at"],
                    }
                    for row in entity_store_rows if row["store_id"] is not None
                ]
        return {
            "templates": template_payloads,
            "currentTemplate": current_template,
            "draftTemplate": draft_template,
            "currentRule": _rule_to_api(row_to_dict(current_rule)),
            "draftRule": _rule_draft_to_api(row_to_dict(rule_draft)),
            "rules": [
                {
                    "code": code,
                    "name": name,
                    "category": category,
                    "summary": summary,
                    "status": status,
                    "source": source,
                }
                for code, name, category, summary, status, source in RULE_CATALOG
            ],
            "baseData": base_data,
            "masterData": master_data,
            "mappingTypes": _mapping_types_to_api(),
            "valueMappings": [_value_mapping_to_api(row_to_dict(row)) for row in mapping_rows],
            "unmappedValues": [_unmapped_value_to_api(row_to_dict(row)) for row in unmapped_rows],
            "releaseBoundary": {
                "templateMaintenance": "available",
                "ruleMaintenance": "available",
                "baseDataMaintenance": "available",
            },
        }

    def master_data_options(self):
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT e.id AS entity_id, e.name AS entity_name, e.status AS entity_status,
                       s.id AS store_id, s.name AS store_name, s.platform_code,
                       s.status AS store_status, s.created_at, s.updated_at,
                       COUNT(t.id) AS task_count, MAX(t.updated_at) AS last_used_at
                FROM business_entities e
                LEFT JOIN platform_stores s ON s.entity_id = e.id
                LEFT JOIN tasks t ON t.store_id = s.id AND t.is_sample = 0
                GROUP BY e.id, s.id
                ORDER BY e.name, s.name
                """
            ).fetchall()
        return {"entities": _master_data_to_api(rows)}

    def create_business_entity(self, payload):
        if not isinstance(payload, dict):
            raise ValidationError("主体资料格式不正确")
        name = clean_text(payload.get("name"), "企业主体")
        now = utc_now()
        with connect(self.database_path) as connection:
            existing = connection.execute(
                "SELECT * FROM business_entities WHERE name = ?", (name,)
            ).fetchone()
            if existing is not None:
                if existing["status"] == "inactive":
                    connection.execute(
                        "UPDATE business_entities SET status = 'active', updated_at = ? WHERE id = ?",
                        (now, existing["id"]),
                    )
            else:
                entity_id = "entity-{}".format(uuid.uuid4().hex)
                connection.execute(
                    """
                    INSERT INTO business_entities (id, name, status, created_at, updated_at)
                    VALUES (?, ?, 'active', ?, ?)
                    """,
                    (entity_id, name, now, now),
                )
                append_operation(
                    connection, None, "business_entity_created",
                    details={"entityId": entity_id, "name": name},
                )
        return self.master_data_options()

    def create_platform_store(self, payload):
        if not isinstance(payload, dict):
            raise ValidationError("店铺资料格式不正确")
        entity_id = clean_text(payload.get("entityId"), "企业主体编号", 100)
        name = clean_text(payload.get("name"), "店铺名称")
        now = utc_now()
        with connect(self.database_path) as connection:
            entity = connection.execute(
                "SELECT * FROM business_entities WHERE id = ? AND status = 'active'",
                (entity_id,),
            ).fetchone()
            if entity is None:
                raise ValidationError("请选择正在使用的企业主体")
            existing = connection.execute(
                """
                SELECT * FROM platform_stores
                WHERE entity_id = ? AND platform_code = 'DOUYIN' AND name = ?
                """,
                (entity_id, name),
            ).fetchone()
            if existing is not None:
                if existing["status"] == "inactive":
                    connection.execute(
                        "UPDATE platform_stores SET status = 'active', updated_at = ? WHERE id = ?",
                        (now, existing["id"]),
                    )
            else:
                store_id = "store-{}".format(uuid.uuid4().hex)
                connection.execute(
                    """
                    INSERT INTO platform_stores (
                        id, entity_id, platform_code, name, status, created_at, updated_at
                    ) VALUES (?, ?, 'DOUYIN', ?, 'active', ?, ?)
                    """,
                    (store_id, entity_id, name, now, now),
                )
                append_operation(
                    connection, None, "platform_store_created",
                    details={"storeId": store_id, "entityId": entity_id, "name": name},
                )
        return self.master_data_options()

    def update_platform_store_status(self, store_id, payload):
        store_id = clean_text(store_id, "店铺编号", 100)
        if not isinstance(payload, dict) or payload.get("status") not in ("active", "inactive"):
            raise ValidationError("店铺状态只能是启用或停用")
        status = payload["status"]
        now = utc_now()
        with connect(self.database_path) as connection:
            store = connection.execute(
                "SELECT * FROM platform_stores WHERE id = ?", (store_id,)
            ).fetchone()
            if store is None:
                raise NotFoundError("没有找到这个店铺")
            connection.execute(
                "UPDATE platform_stores SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, store_id),
            )
            append_operation(
                connection, None, "platform_store_status_changed",
                details={"storeId": store_id, "status": status},
            )
        return self.master_data_options()

    def create_platform_value_mapping(self, payload):
        if not isinstance(payload, dict):
            raise ValidationError("平台值映射格式不正确")
        mapping_type = clean_text(payload.get("mappingType"), "映射类型", 50)
        definition = VALUE_MAPPING_TYPES.get(mapping_type)
        if definition is None:
            raise ValidationError("映射类型不支持")
        source_value = clean_text(payload.get("sourceValue"), "平台原值", 200)
        standard_code = clean_text(payload.get("standardCode"), "标准值", 100)
        standard = next(
            (item for item in definition["standards"] if item["code"] == standard_code),
            None,
        )
        if standard is None:
            raise ValidationError("请选择系统支持的标准值")
        effective_from = _validate_date(payload.get("effectiveFrom"), "生效日期")
        notes = clean_text(payload.get("notes"), "映射说明", 500)
        now = utc_now()
        with connect(self.database_path) as connection:
            current = connection.execute(
                """
                SELECT * FROM platform_value_mappings
                WHERE mapping_type = ? AND source_value = ? AND is_current = 1
                """,
                (mapping_type, source_value),
            ).fetchone()
            if current is not None and (
                current["standard_code"] == standard_code
                and current["effective_from"] == effective_from
            ):
                raise ValidationError("当前映射已经是这个标准值和生效日期")
            version_number = connection.execute(
                """
                SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version
                FROM platform_value_mappings
                WHERE mapping_type = ? AND source_value = ?
                """,
                (mapping_type, source_value),
            ).fetchone()["next_version"]
            connection.execute(
                """
                UPDATE platform_value_mappings SET is_current = 0
                WHERE mapping_type = ? AND source_value = ? AND is_current = 1
                """,
                (mapping_type, source_value),
            )
            mapping_id = "mapping-{}".format(uuid.uuid4().hex)
            connection.execute(
                """
                INSERT INTO platform_value_mappings (
                    id, mapping_type, source_value, standard_code, standard_name,
                    canonical_value, version_number, version_label, effective_from,
                    is_current, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    mapping_id, mapping_type, source_value, standard_code,
                    standard["name"], standard["canonicalValue"], version_number,
                    "V{}".format(version_number), effective_from, notes, now,
                ),
            )
            connection.execute(
                """
                UPDATE unmapped_platform_values
                SET status = 'mapped', resolved_mapping_id = ?, resolved_at = ?
                WHERE mapping_type = ? AND source_value = ? AND status = 'pending'
                """,
                (mapping_id, now, mapping_type, source_value),
            )
            append_operation(
                connection, None, "platform_value_mapping_activated", reason=notes,
                details={
                    "mappingId": mapping_id,
                    "mappingType": mapping_type,
                    "sourceValue": source_value,
                    "standardCode": standard_code,
                    "versionLabel": "V{}".format(version_number),
                    "effectiveFrom": effective_from,
                    "existingImportPolicy": "keep_original_mapping_snapshot",
                },
            )
        return self.configuration_center()

    def create_rule_draft(self):
        now = utc_now()
        with connect(self.database_path) as connection:
            existing = connection.execute(
                "SELECT * FROM rule_version_drafts ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if existing is not None:
                return _rule_draft_to_api(row_to_dict(existing))
            current = connection.execute(
                """
                SELECT * FROM rule_versions
                WHERE status = 'current'
                ORDER BY created_at DESC LIMIT 1
                """
            ).fetchone()
            if current is None:
                raise RuntimeError("没有可复制的生效规则")
            version_rows = connection.execute(
                """
                SELECT version_label FROM rule_versions
                UNION ALL
                SELECT version_label FROM rule_version_drafts
                """
            ).fetchall()
            version_label = _next_version_label(
                [row["version_label"] for row in version_rows]
            )
            draft_id = "rule-draft-{}".format(uuid.uuid4().hex)
            connection.execute(
                """
                INSERT INTO rule_version_drafts (
                    id, source_rule_version_id, version_label, tolerance_cents,
                    refund_auto_group_seconds, refund_candidate_seconds,
                    settlement_wait_days, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id, current["id"], version_label,
                    current["tolerance_cents"], current["refund_auto_group_seconds"],
                    current["refund_candidate_seconds"],
                    current["settlement_wait_days"],
                    "从{}复制；说明本次参数变更原因。".format(
                        current["version_label"]
                    ),
                    now, now,
                ),
            )
            append_operation(
                connection, None, "rule_draft_created",
                details={
                    "ruleDraftId": draft_id,
                    "sourceRuleVersionId": current["id"],
                    "versionLabel": version_label,
                },
            )
            row = connection.execute(
                "SELECT * FROM rule_version_drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            return _rule_draft_to_api(row_to_dict(row))

    def update_rule_draft(self, draft_id, payload):
        draft_id = clean_text(draft_id, "规则草稿编号", 100)
        if not isinstance(payload, dict):
            raise ValidationError("规则参数格式不正确")
        parameters = _validate_rule_parameters(payload)
        notes = _clean_optional_text(payload.get("notes"), "变更说明", 500)
        now = utc_now()
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT id FROM rule_version_drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("没有找到这个规则草稿")
            connection.execute(
                """
                UPDATE rule_version_drafts
                SET tolerance_cents = ?, refund_auto_group_seconds = ?,
                    refund_candidate_seconds = ?, settlement_wait_days = ?,
                    notes = ?, updated_at = ?, last_tested_at = NULL,
                    last_test_status = NULL, last_test_summary_json = NULL
                WHERE id = ?
                """,
                (
                    parameters["tolerance_cents"],
                    parameters["refund_auto_group_seconds"],
                    parameters["refund_candidate_seconds"],
                    parameters["settlement_wait_days"],
                    notes, now, draft_id,
                ),
            )
            append_operation(
                connection, None, "rule_draft_updated",
                details={"ruleDraftId": draft_id, **_rule_parameters_to_api(parameters)},
            )
            updated = connection.execute(
                "SELECT * FROM rule_version_drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            return _rule_draft_to_api(row_to_dict(updated))

    def test_rule_draft(self, draft_id):
        draft_id = clean_text(draft_id, "规则草稿编号", 100)
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM rule_version_drafts WHERE id = ?", (draft_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("没有找到这个规则草稿")
        draft = row_to_dict(row)
        parameters = _rule_parameters_from_row(draft)
        result = run_fixed_cases(
            Path(__file__).resolve().parent.parent, parameters=parameters
        )
        now = utc_now()
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE rule_version_drafts
                SET last_tested_at = ?, last_test_status = ?,
                    last_test_summary_json = ?
                WHERE id = ? AND updated_at = ?
                """,
                (
                    now, result["status"],
                    json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                    draft_id, draft["updated_at"],
                ),
            )
            if cursor.rowcount != 1:
                raise ValidationError("试算期间草稿已被修改，请重新试算")
            append_operation(
                connection, None, "rule_draft_tested",
                details={
                    "ruleDraftId": draft_id,
                    "status": result["status"],
                    "passedCount": result["passedCount"],
                    "failedCount": result["failedCount"],
                },
            )
        return {"fixedCases": result}

    def activate_rule_draft(self, draft_id, payload):
        draft_id = clean_text(draft_id, "规则草稿编号", 100)
        if not isinstance(payload, dict) or payload.get("confirmed") is not True:
            raise ValidationError("启用新规则前需要明确确认")
        now = utc_now()
        with connect(self.database_path) as connection:
            draft = connection.execute(
                "SELECT * FROM rule_version_drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            if draft is None:
                raise NotFoundError("没有找到这个规则草稿")
            if not draft["notes"]:
                raise ValidationError("请先填写规则变更说明")
            if draft["last_test_status"] != "passed" or not draft["last_tested_at"]:
                raise ValidationError("请先让23个固定案例全部通过")
            current = connection.execute(
                "SELECT id, version_label FROM rule_versions WHERE status = 'current'"
            ).fetchone()
            connection.execute(
                "UPDATE rule_versions SET status = 'inactive' WHERE status = 'current'"
            )
            new_rule_id = "rule-{}".format(uuid.uuid4().hex)
            connection.execute(
                """
                INSERT INTO rule_versions (
                    id, version_label, tolerance_cents, refund_auto_group_seconds,
                    refund_candidate_seconds, settlement_wait_days, status,
                    created_at, notes, activated_at, fixed_case_summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'current', ?, ?, ?, ?)
                """,
                (
                    new_rule_id, draft["version_label"], draft["tolerance_cents"],
                    draft["refund_auto_group_seconds"],
                    draft["refund_candidate_seconds"],
                    draft["settlement_wait_days"], now, draft["notes"], now,
                    draft["last_test_summary_json"],
                ),
            )
            connection.execute(
                "DELETE FROM rule_version_drafts WHERE id = ?", (draft_id,)
            )
            append_operation(
                connection, None, "rule_version_activated",
                reason=draft["notes"],
                details={
                    "ruleVersionId": new_rule_id,
                    "versionLabel": draft["version_label"],
                    "previousRuleVersionId": current["id"] if current else None,
                    "previousVersionLabel": current["version_label"] if current else None,
                    "existingTaskPolicy": "keep_original_rule_version",
                    **_rule_parameters_to_api(_rule_parameters_from_row(draft)),
                },
            )
        return self.configuration_center()

    def create_bill_template_draft(self):
        now = utc_now()
        with connect(self.database_path) as connection:
            existing = connection.execute(
                "SELECT * FROM bill_template_versions WHERE status = 'draft' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if existing is not None:
                return _bill_template_to_api(connection, row_to_dict(existing))
            current = _load_bill_template(connection, status="current")
            if current is None:
                raise RuntimeError("没有可复制的生效账单模板")
            version_rows = connection.execute(
                """
                SELECT version_label FROM bill_template_versions
                WHERE platform_code = ? AND template_code = ?
                """,
                (current["platform_code"], current["template_code"]),
            ).fetchall()
            version_label = _next_version_label(
                [row["version_label"] for row in version_rows]
            )
            draft_id = "template-{}".format(uuid.uuid4().hex)
            connection.execute(
                """
                INSERT INTO bill_template_versions (
                    id, platform_code, template_code, version_label, name, status,
                    notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?)
                """,
                (
                    draft_id,
                    current["platform_code"],
                    current["template_code"],
                    version_label,
                    current["name"],
                    "从{}复制；修改后必须用样例工作簿测试通过才能启用。".format(
                        current["version_label"]
                    ),
                    now,
                    now,
                ),
            )
            for source_sheet in current["sheets"]:
                sheet_id = "template-sheet-{}".format(uuid.uuid4().hex)
                connection.execute(
                    """
                    INSERT INTO bill_template_sheets (
                        id, template_version_id, standard_sheet_code, display_name,
                        source_sheet_name, source_sheet_aliases_json, header_row,
                        data_start_row, baseline_rows, baseline_columns, required, sort_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sheet_id, draft_id, source_sheet["standard_sheet_code"],
                        source_sheet["display_name"], source_sheet["source_sheet_name"],
                        source_sheet["source_sheet_aliases_json"], source_sheet["header_row"],
                        source_sheet["data_start_row"], source_sheet["baseline_rows"],
                        source_sheet["baseline_columns"], source_sheet["required"],
                        source_sheet["sort_order"],
                    ),
                )
                for source_field in source_sheet["fields"]:
                    connection.execute(
                        """
                        INSERT INTO bill_template_fields (
                            id, sheet_id, standard_field_code, display_name,
                            source_header, source_aliases_json, data_type, required, sort_order
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "template-field-{}".format(uuid.uuid4().hex),
                            sheet_id, source_field["standard_field_code"],
                            source_field["display_name"], source_field["source_header"],
                            source_field["source_aliases_json"], source_field["data_type"],
                            source_field["required"], source_field["sort_order"],
                        ),
                    )
            append_operation(
                connection, None, "bill_template_draft_created",
                details={"templateVersionId": draft_id, "versionLabel": version_label},
            )
            row = connection.execute(
                "SELECT * FROM bill_template_versions WHERE id = ?", (draft_id,)
            ).fetchone()
            return _bill_template_to_api(connection, row_to_dict(row))

    def update_bill_template_draft(self, template_id, payload):
        template_id = clean_text(template_id, "模板版本编号", 100)
        if not isinstance(payload, dict):
            raise ValidationError("模板配置格式不正确")
        now = utc_now()
        with connect(self.database_path) as connection:
            template = _load_bill_template(connection, template_id=template_id)
            if template is None:
                raise NotFoundError("没有找到这个账单模板")
            if template["status"] != "draft":
                raise ValidationError("已发布模板不能直接修改，请先复制新版本")
            updates = payload.get("sheets")
            if not isinstance(updates, list) or not updates:
                raise ValidationError("请至少提交一张工作表的配置")
            sheets_by_id = {item["id"]: item for item in template["sheets"]}
            for update in updates:
                if not isinstance(update, dict) or update.get("id") not in sheets_by_id:
                    raise ValidationError("工作表配置不属于当前草稿")
                source_sheet_name = clean_text(
                    update.get("sourceSheetName"), "平台工作表名", 100
                )
                sheet_aliases = _validate_aliases(
                    update.get("sourceSheetAliases", []), "工作表别名"
                )
                header_row = _validate_positive_int(update.get("headerRow"), "表头行", 1000)
                data_start_row = _validate_positive_int(
                    update.get("dataStartRow"), "数据起始行", 1000000
                )
                if data_start_row <= header_row:
                    raise ValidationError("数据起始行必须在表头行之后")
                connection.execute(
                    """
                    UPDATE bill_template_sheets
                    SET source_sheet_name = ?, source_sheet_aliases_json = ?,
                        header_row = ?, data_start_row = ?
                    WHERE id = ? AND template_version_id = ?
                    """,
                    (
                        source_sheet_name, json.dumps(sheet_aliases, ensure_ascii=False),
                        header_row, data_start_row, update["id"], template_id,
                    ),
                )
                fields_by_id = {
                    item["id"]: item for item in sheets_by_id[update["id"]]["fields"]
                }
                field_updates = update.get("fields") or []
                proposed_names = {}
                for current_field in fields_by_id.values():
                    proposed_names[current_field["id"]] = (
                        current_field["source_header"],
                        json.loads(current_field["source_aliases_json"] or "[]"),
                    )
                for field_update in field_updates:
                    if not isinstance(field_update, dict) or field_update.get("id") not in fields_by_id:
                        raise ValidationError("字段配置不属于当前工作表")
                    source_header = clean_text(
                        field_update.get("sourceHeader"), "平台字段名", 120
                    )
                    aliases = _validate_aliases(
                        field_update.get("sourceAliases", []), "字段别名"
                    )
                    proposed_names[field_update["id"]] = (source_header, aliases)
                seen_sources = {}
                for field_id, (source_header, aliases) in proposed_names.items():
                    canonical = fields_by_id[field_id]["display_name"]
                    for source_name in [source_header, *aliases]:
                        if source_name in seen_sources and seen_sources[source_name] != canonical:
                            raise ValidationError(
                                "字段{}同时映射到{}和{}".format(
                                    source_name, seen_sources[source_name], canonical
                                )
                            )
                        seen_sources[source_name] = canonical
                for field_id, (source_header, aliases) in proposed_names.items():
                    connection.execute(
                        """
                        UPDATE bill_template_fields
                        SET source_header = ?, source_aliases_json = ?
                        WHERE id = ? AND sheet_id = ?
                        """,
                        (
                            source_header, json.dumps(aliases, ensure_ascii=False),
                            field_id, update["id"],
                        ),
                    )
            name = payload.get("name")
            if name is not None:
                name = clean_text(name, "模板名称", 100)
            else:
                name = template["name"]
            notes = _clean_optional_text(payload.get("notes"), "模板说明", 500)
            connection.execute(
                """
                UPDATE bill_template_versions
                SET name = ?, notes = ?, updated_at = ?, last_tested_at = NULL,
                    last_test_status = NULL, last_test_file_name = NULL,
                    last_test_summary_json = NULL
                WHERE id = ?
                """,
                (name, notes, now, template_id),
            )
            append_operation(
                connection, None, "bill_template_draft_updated",
                details={"templateVersionId": template_id},
            )
            row = connection.execute(
                "SELECT * FROM bill_template_versions WHERE id = ?", (template_id,)
            ).fetchone()
            return _bill_template_to_api(connection, row_to_dict(row))

    def test_bill_template(self, template_id, original_name, content):
        template_id = clean_text(template_id, "模板版本编号", 100)
        file_name = _validate_file_name(original_name)
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise ValidationError("请选择测试用Excel文件")
        if len(content) > MAX_WORKBOOK_BYTES:
            raise ValidationError("Excel文件不能超过50MB")
        with connect(self.database_path) as connection:
            template = _load_bill_template(connection, template_id=template_id)
        if template is None:
            raise NotFoundError("没有找到这个账单模板")
        if template["status"] != "draft":
            raise ValidationError("只能测试未发布的模板草稿")
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".xlsx", prefix="template-test-",
                dir=str(self.upload_dir), delete=False
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            inspection = inspect_workbook(
                temporary_path, _bill_template_definitions(template)
            )
        except WorkbookInspectionError as exc:
            raise ValidationError(str(exc))
        finally:
            if temporary_path is not None:
                _remove_if_present(temporary_path)
        inspection["templateVersionId"] = template_id
        inspection["templateVersionLabel"] = template["version_label"]
        now = utc_now()
        with connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE bill_template_versions
                SET last_tested_at = ?, last_test_status = ?, last_test_file_name = ?,
                    last_test_summary_json = ?
                WHERE id = ? AND status = 'draft'
                """,
                (
                    now, inspection["status"], file_name,
                    json.dumps(inspection, ensure_ascii=False, separators=(",", ":")),
                    template_id,
                ),
            )
            append_operation(
                connection, None, "bill_template_tested",
                details={
                    "templateVersionId": template_id,
                    "fileName": file_name,
                    "status": inspection["status"],
                },
            )
        return {"inspection": inspection}

    def activate_bill_template(self, template_id, payload):
        template_id = clean_text(template_id, "模板版本编号", 100)
        if not isinstance(payload, dict) or payload.get("confirmed") is not True:
            raise ValidationError("启用新模板前需要明确确认")
        now = utc_now()
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM bill_template_versions WHERE id = ?", (template_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("没有找到这个账单模板")
            if row["status"] != "draft":
                raise ValidationError("只能启用模板草稿")
            if row["last_test_status"] != "passed" or not row["last_tested_at"]:
                raise ValidationError("请先用平台样例文件测试通过再启用")
            connection.execute(
                """
                UPDATE bill_template_versions
                SET status = 'inactive', updated_at = ?
                WHERE platform_code = ? AND template_code = ? AND status = 'current'
                """,
                (now, row["platform_code"], row["template_code"]),
            )
            connection.execute(
                """
                UPDATE bill_template_versions
                SET status = 'current', updated_at = ?, activated_at = ?
                WHERE id = ?
                """,
                (now, now, template_id),
            )
            append_operation(
                connection, None, "bill_template_activated",
                details={
                    "templateVersionId": template_id,
                    "versionLabel": row["version_label"],
                    "testFileName": row["last_test_file_name"],
                },
            )
        return self.configuration_center()

    def _definitions_for_template_version(self, template_version_id):
        with connect(self.database_path) as connection:
            template = _load_bill_template(
                connection, template_id=template_version_id or DEFAULT_TEMPLATE_ID
            )
        if template is None:
            raise RuntimeError("导入文件对应的账单模板已缺失")
        return _bill_template_definitions(template)

    def list_tasks(self):
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT t.id, t.entity_name, t.store_name, t.period, t.status, t.rule_version_id,
                       t.is_sample,
                       r.version_label AS rule_version_label,
                       t.created_at, t.updated_at, t.completed_at, t.reopened_at
                FROM tasks t
                JOIN rule_versions r ON r.id = t.rule_version_id
                ORDER BY t.period DESC, t.created_at DESC
                """
            ).fetchall()
        return [_task_to_api(row_to_dict(row)) for row in rows]

    def create_task(self, payload):
        if not isinstance(payload, dict):
            raise ValidationError("请求内容必须是对象")
        period = validate_period(payload.get("period"))
        task_id = "task-{}".format(uuid.uuid4().hex)
        now = utc_now()

        with connect(self.database_path) as connection:
            store_id = payload.get("storeId")
            if store_id:
                store_id = clean_text(store_id, "店铺编号", 100)
                master = connection.execute(
                    """
                    SELECT s.id AS store_id, s.name AS store_name,
                           e.id AS entity_id, e.name AS entity_name
                    FROM platform_stores s
                    JOIN business_entities e ON e.id = s.entity_id
                    WHERE s.id = ? AND s.status = 'active' AND e.status = 'active'
                    """,
                    (store_id,),
                ).fetchone()
                if master is None:
                    raise ValidationError("请选择正在使用的主体和店铺")
                entity_id = master["entity_id"]
                entity_name = master["entity_name"]
                store_name = master["store_name"]
            else:
                # Retain compatibility for local scripts and old API clients while
                # the browser now uses maintained store IDs.
                entity_name = clean_text(payload.get("entityName"), "企业主体")
                store_name = clean_text(payload.get("storeName"), "店铺名称")
                entity_id, store_id = _find_or_create_master_store(
                    connection, entity_name, store_name, now
                )
            current_rule = connection.execute(
                "SELECT id FROM rule_versions WHERE status = 'current' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if current_rule is None:
                raise RuntimeError("没有可用的规则版本")
            try:
                connection.execute(
                    """
                    INSERT INTO tasks (
                        id, entity_name, store_name, period, status, rule_version_id,
                        created_at, updated_at, is_sample, entity_id, store_id
                    ) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        task_id, entity_name, store_name, period, current_rule["id"],
                        now, now, entity_id, store_id,
                    ),
                )
            except sqlite3.IntegrityError:
                existing = connection.execute(
                    """
                    SELECT t.id, t.entity_name, t.store_name, t.period, t.status, t.rule_version_id,
                           t.is_sample,
                           r.version_label AS rule_version_label,
                           t.created_at, t.updated_at, t.completed_at, t.reopened_at
                    FROM tasks t
                    JOIN rule_versions r ON r.id = t.rule_version_id
                    WHERE t.entity_name = ? AND t.store_name = ? AND t.period = ?
                    """,
                    (entity_name, store_name, period),
                ).fetchone()
                if existing is not None:
                    raise DuplicateTaskError(_task_to_api(row_to_dict(existing)))
                raise

            append_operation(
                connection,
                task_id,
                "task_created",
                details={
                    "entityId": entity_id, "entityName": entity_name,
                    "storeId": store_id, "storeName": store_name, "period": period,
                },
            )
            row = connection.execute(
                """
                SELECT t.id, t.entity_name, t.store_name, t.period, t.status, t.rule_version_id,
                       t.is_sample,
                       r.version_label AS rule_version_label,
                       t.created_at, t.updated_at, t.completed_at, t.reopened_at
                FROM tasks t
                JOIN rule_versions r ON r.id = t.rule_version_id
                WHERE t.id = ?
                """,
                (task_id,),
            ).fetchone()
        return _task_to_api(row_to_dict(row))

    def load_sample(self):
        if self.sample_workbook_path is None or not self.sample_workbook_path.is_file():
            raise NotFoundError("没有找到本机样例数据文件")

        with connect(self.database_path) as connection:
            existing = connection.execute(
                """
                SELECT t.id, t.entity_name, t.store_name, t.period, t.status, t.rule_version_id,
                       t.is_sample, r.version_label AS rule_version_label,
                       t.created_at, t.updated_at, t.completed_at, t.reopened_at
                FROM tasks t
                JOIN rule_versions r ON r.id = t.rule_version_id
                WHERE t.is_sample = 1
                ORDER BY t.created_at DESC
                LIMIT 1
                """
            ).fetchone()
        if existing is not None:
            return {"created": False, **self.get_task(existing["id"])}

        task = self._create_sample_task()
        try:
            content = self.sample_workbook_path.read_bytes()
            result = self.upload_workbook(
                task["id"], "抖店练习数据.xlsx", content
            )
        except Exception:
            with connect(self.database_path) as connection:
                connection.execute("DELETE FROM tasks WHERE id = ?", (task["id"],))
            task_directory = self.upload_dir / task["id"]
            _remove_empty_directory(task_directory)
            raise
        return {"created": True, "task": result["task"], "files": [result["file"]]}

    def _create_sample_task(self):
        task_id = "sample-{}".format(uuid.uuid4().hex)
        now = utc_now()
        with connect(self.database_path) as connection:
            current_rule = connection.execute(
                "SELECT id FROM rule_versions WHERE status = 'current' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if current_rule is None:
                raise RuntimeError("没有可用的规则版本")
            connection.execute(
                """
                INSERT INTO tasks (
                    id, entity_name, store_name, period, status, rule_version_id,
                    created_at, updated_at, is_sample
                ) VALUES (?, '样例主体', '抖店样例店铺', '2023-12', 'draft', ?, ?, ?, 1)
                """,
                (task_id, current_rule["id"], now, now),
            )
            append_operation(
                connection,
                task_id,
                "sample_loaded",
                details={"source": "bundled_practice_workbook"},
            )
            row = _select_task(connection, task_id)
        return _task_to_api(row_to_dict(row))

    def get_task(self, task_id):
        task_id = clean_text(task_id, "任务编号", 80)
        with connect(self.database_path) as connection:
            task = _select_task(connection, task_id)
            if task is None:
                raise NotFoundError("没有找到这个对账任务")
            files = connection.execute(
                """
                SELECT f.id, f.task_id, f.original_name, f.content_sha256, f.size_bytes,
                       f.replacement_reason, f.created_at, f.template_version_id,
                       bt.version_label AS template_version_label,
                       bt.name AS template_name,
                       i.status AS inspection_status, i.summary_json,
                       d.id AS data_import_id,
                       d.status AS data_import_status,
                       d.summary_json AS data_import_summary_json,
                       a.status AS amount_check_status,
                       a.summary_json AS amount_check_summary_json,
                       a.tolerance_cents AS amount_check_tolerance_cents,
                       rr.status AS reconciliation_status,
                       rr.summary_json AS reconciliation_summary_json,
                       frr.status AS refund_reconciliation_status,
                       frr.summary_json AS refund_reconciliation_summary_json,
                       srr.status AS supplementary_reconciliation_status,
                       srr.summary_json AS supplementary_reconciliation_summary_json
                FROM file_versions f
                JOIN workbook_inspections i ON i.file_version_id = f.id
                LEFT JOIN bill_template_versions bt ON bt.id = f.template_version_id
                LEFT JOIN data_imports d ON d.file_version_id = f.id
                LEFT JOIN amount_check_runs a ON a.import_id = d.id
                LEFT JOIN reconciliation_runs rr ON rr.import_id = d.id
                LEFT JOIN refund_reconciliation_runs frr ON frr.import_id = d.id
                LEFT JOIN supplementary_reconciliation_runs srr
                       ON srr.import_id = d.id AND srr.is_current = 1
                WHERE f.task_id = ?
                ORDER BY f.created_at DESC, f.id DESC
                """,
                (task_id,),
            ).fetchall()
            completion = _build_completion_summary(connection, task_id)
            lifecycle_rows = connection.execute(
                """
                SELECT id, action, reason, summary_json, rule_version_id, created_at
                FROM period_lifecycle_events
                WHERE task_id = ?
                ORDER BY created_at DESC, rowid DESC
                """,
                (task_id,),
            ).fetchall()
            platform_balance = _select_platform_balance_snapshot(connection, task_id)
            pending_settlement = _select_pending_settlement_snapshot(connection, task_id)
        return {
            "task": _task_to_api(row_to_dict(task)),
            "files": [_file_to_api(row_to_dict(row), self.database_path) for row in files],
            "completion": completion,
            "platformBalance": _platform_balance_snapshot_to_api(platform_balance),
            "pendingSettlement": _pending_settlement_snapshot_to_api(pending_settlement),
            "lifecycleEvents": [_period_event_to_api(row) for row in lifecycle_rows],
        }

    def get_completion_summary(self, task_id):
        task_id = clean_text(task_id, "任务编号", 80)
        with connect(self.database_path) as connection:
            if _select_task(connection, task_id) is None:
                raise NotFoundError("没有找到这个对账任务")
            return {"completion": _build_completion_summary(connection, task_id)}

    def get_operating_report_readiness(self, task_id):
        task_id = clean_text(task_id, "任务编号", 80)
        with connect(self.database_path) as connection:
            task = _select_task(connection, task_id)
            if task is None:
                raise NotFoundError("没有找到这个对账任务")
            latest = connection.execute(
                """
                SELECT f.id AS file_id, f.original_name, f.created_at,
                       d.id AS import_id, d.status AS import_status,
                       d.total_record_count, d.summary_json AS import_summary_json
                FROM file_versions f
                LEFT JOIN data_imports d ON d.file_version_id = f.id
                WHERE f.task_id = ?
                ORDER BY f.created_at DESC, f.id DESC
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
            records = []
            supplementary_summary = None
            if latest is not None and latest["import_id"]:
                records = connection.execute(
                    """
                    SELECT record_type,
                           COALESCE(mapped_values_json, raw_values_json) AS values_json
                    FROM source_records
                    WHERE import_id = ?
                    ORDER BY id
                    """,
                    (latest["import_id"],),
                ).fetchall()
                supplementary = connection.execute(
                    """
                    SELECT summary_json
                    FROM supplementary_reconciliation_runs
                    WHERE import_id = ? AND is_current = 1
                    LIMIT 1
                    """,
                    (latest["import_id"],),
                ).fetchone()
                if supplementary is not None:
                    supplementary_summary = _json_object(supplementary["summary_json"])
            platform_balance = _select_platform_balance_snapshot(connection, task_id)
            pending_settlement = _select_pending_settlement_snapshot(connection, task_id)
            operating_evidence_rows = _select_operating_evidence_rows(connection, task_id)
        operating_evidence = _build_operating_evidence_catalog(operating_evidence_rows)
        return _build_operating_report_readiness(
            row_to_dict(task),
            row_to_dict(latest),
            records,
            supplementary_summary,
            platform_balance,
            pending_settlement,
            operating_evidence,
        )

    def get_operating_evidence(self, task_id):
        task_id = clean_text(task_id, "任务编号", 80)
        with connect(self.database_path) as connection:
            if _select_task(connection, task_id) is None:
                raise NotFoundError("没有找到这个对账任务")
            rows = _select_operating_evidence_rows(connection, task_id)
        return {"operatingEvidence": _build_operating_evidence_catalog(rows)}

    def get_operating_evidence_results(
        self, task_id, evidence_type, status="all", page=1, page_size=50
    ):
        task_id = clean_text(task_id, "任务编号", 80)
        evidence_type = clean_text(evidence_type, "资料类型", 40)
        if evidence_type not in OPERATING_EVIDENCE_TYPES:
            raise ValidationError("这个经营资料类型不支持")
        if status not in ("all", "matched", "needs_attention"):
            raise ValidationError("经营资料明细状态不支持")
        try:
            page = max(1, int(page))
            page_size = min(100, max(1, int(page_size)))
        except (TypeError, ValueError):
            raise ValidationError("分页参数不正确")
        with connect(self.database_path) as connection:
            if _select_task(connection, task_id) is None:
                raise NotFoundError("没有找到这个对账任务")
            run = connection.execute(
                """
                SELECT r.*, f.original_name
                FROM operating_evidence_runs r
                JOIN operating_evidence_files f ON f.id = r.file_id
                WHERE r.task_id = ? AND r.evidence_type = ? AND r.is_current = 1
                LIMIT 1
                """,
                (task_id, evidence_type),
            ).fetchone()
            if run is None:
                raise NotFoundError("这类资料还没有可查看的映射结果")
            clauses = ["run_id = ?"]
            params = [run["id"]]
            if status != "all":
                clauses.append("status = ?")
                params.append(status)
            total = connection.execute(
                "SELECT COUNT(*) AS count FROM operating_evidence_rows WHERE {}".format(
                    " AND ".join(clauses)
                ),
                params,
            ).fetchone()["count"]
            rows = connection.execute(
                """
                SELECT * FROM operating_evidence_rows
                WHERE {}
                ORDER BY row_number
                LIMIT ? OFFSET ?
                """.format(" AND ".join(clauses)),
                params + [page_size, (page - 1) * page_size],
            ).fetchall()
        return {
            "evidenceType": evidence_type,
            "label": OPERATING_EVIDENCE_TYPES[evidence_type]["label"],
            "run": _operating_evidence_run_to_api(run),
            "rows": [_operating_evidence_row_to_api(row) for row in rows],
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": total,
                "totalPages": max(1, (total + page_size - 1) // page_size),
            },
        }

    def upload_operating_evidence_file(
        self, task_id, evidence_type, original_name, content, replacement_reason=None
    ):
        task_id = clean_text(task_id, "任务编号", 80)
        evidence_type = clean_text(evidence_type, "资料类型", 40)
        definition = OPERATING_EVIDENCE_TYPES.get(evidence_type)
        if definition is None:
            raise ValidationError("这个经营资料类型不支持")
        file_name = _validate_operating_evidence_file_name(original_name)
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise ValidationError("请选择要提交的经营资料文件")
        if len(content) > MAX_WORKBOOK_BYTES:
            raise ValidationError("经营资料文件不能超过50MB")
        reason = _clean_optional_text(replacement_reason, "替换说明", 300)
        digest = hashlib.sha256(content).hexdigest()
        with connect(self.database_path) as connection:
            task = _select_task(connection, task_id)
            if task is None:
                raise NotFoundError("没有找到这个对账任务")
            if task["status"] == "completed":
                raise ValidationError("本期已完成，请先填写原因重新打开")
            duplicate = connection.execute(
                """
                SELECT 1 FROM operating_evidence_files
                WHERE task_id = ? AND evidence_type = ? AND content_sha256 = ?
                """,
                (task_id, evidence_type, digest),
            ).fetchone()
            if duplicate is not None:
                raise ValidationError("这份{}资料已经提交过".format(definition["shortLabel"]))
            previous = connection.execute(
                """
                SELECT 1 FROM operating_evidence_files
                WHERE task_id = ? AND evidence_type = ? LIMIT 1
                """,
                (task_id, evidence_type),
            ).fetchone()
        if previous is not None and reason is None:
            raise ValidationError("再次提交{}时请填写替换说明".format(definition["shortLabel"]))

        file_id = "operating-evidence-{}".format(uuid.uuid4().hex)
        suffix = Path(file_name).suffix.lower()
        task_directory = self.upload_dir / task_id / "operating-evidence" / evidence_type
        task_directory.mkdir(parents=True, exist_ok=True)
        temporary_path = task_directory / ".{}.uploading".format(file_id)
        final_path = task_directory / "{}{}".format(file_id, suffix)
        stored_name = "{}/operating-evidence/{}/{}{}".format(
            task_id, evidence_type, file_id, suffix
        )
        calculation = None
        try:
            with temporary_path.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if suffix == ".xlsx":
                with connect(self.database_path) as connection:
                    current_import = connection.execute(
                        """
                        SELECT d.id
                        FROM file_versions f
                        JOIN data_imports d ON d.file_version_id = f.id
                        WHERE f.task_id = ?
                        ORDER BY f.created_at DESC, f.id DESC
                        LIMIT 1
                        """,
                        (task_id,),
                    ).fetchone()
                    valid_suborders = []
                    if current_import is not None:
                        settlement_rows = connection.execute(
                            """
                            SELECT COALESCE(mapped_values_json, raw_values_json) AS values_json
                            FROM source_records
                            WHERE import_id = ? AND record_type = 'settlement'
                            """,
                            (current_import["id"],),
                        ).fetchall()
                        valid_suborders = [
                            normalize_identifier(
                                _json_object(item["values_json"]).get("子订单号")
                            )
                            for item in settlement_rows
                        ]
                try:
                    calculation = calculate_simulated_operating_evidence(
                        temporary_path,
                        evidence_type,
                        task_id,
                        task["period"],
                        task["store_name"],
                        valid_suborders,
                        bool(task["is_sample"]),
                    )
                except WorkbookInspectionError as exc:
                    raise ValidationError(str(exc))
            os.replace(str(temporary_path), str(final_path))
        except Exception:
            _remove_if_present(temporary_path)
            raise

        now = utc_now()
        try:
            with connect(self.database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO operating_evidence_files (
                        id, task_id, evidence_type, original_name, stored_name,
                        content_sha256, size_bytes, replacement_reason,
                        processing_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'received_pending_mapping', ?)
                    """,
                    (
                        file_id, task_id, evidence_type, file_name, stored_name,
                        digest, len(content), reason, now,
                    ),
                )
                append_operation(
                    connection,
                    task_id,
                    "operating_evidence_uploaded",
                    reason=reason,
                    details={
                        "fileId": file_id,
                        "evidenceType": evidence_type,
                        "originalName": file_name,
                        "processingStatus": "received_pending_mapping",
                        "simulationProcessed": bool(calculation),
                    },
                )
                if calculation is None:
                    connection.execute(
                        """
                        UPDATE operating_evidence_runs
                        SET is_current = 0, superseded_at = ?
                        WHERE task_id = ? AND evidence_type = ? AND is_current = 1
                        """,
                        (now, task_id, evidence_type),
                    )
                if calculation is not None:
                    connection.execute(
                        """
                        UPDATE operating_evidence_runs
                        SET is_current = 0, superseded_at = ?
                        WHERE task_id = ? AND evidence_type = ? AND is_current = 1
                        """,
                        (now, task_id, evidence_type),
                    )
                    run_id = "operating-evidence-run-{}".format(uuid.uuid4().hex)
                    connection.execute(
                        """
                        INSERT INTO operating_evidence_runs (
                            id, file_id, task_id, evidence_type, mapping_version,
                            data_mode, status, total_row_count, matched_row_count,
                            attention_count, total_amount_cents, summary_json,
                            is_current, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                        """,
                        (
                            run_id, file_id, task_id, evidence_type,
                            calculation["mappingVersion"], calculation["dataMode"],
                            calculation["status"], calculation["totalRowCount"],
                            calculation["matchedRowCount"], calculation["attentionCount"],
                            calculation["totalAmountCents"],
                            json.dumps(calculation["summary"], ensure_ascii=False), now,
                        ),
                    )
                    for row in calculation["rows"]:
                        connection.execute(
                            """
                            INSERT INTO operating_evidence_rows (
                                id, run_id, file_id, task_id, evidence_type,
                                sheet_name, row_number, primary_identifier,
                                secondary_identifier, status, amount_cents,
                                details_json, raw_values_json, explanation, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                "operating-evidence-row-{}".format(uuid.uuid4().hex),
                                run_id, file_id, task_id, evidence_type,
                                calculation["sheetName"], row["rowNumber"],
                                row["primaryIdentifier"], row["secondaryIdentifier"],
                                row["status"], row["amountCents"],
                                json.dumps(row["details"], ensure_ascii=False),
                                json.dumps(row["rawValues"], ensure_ascii=False),
                                row["explanation"], now,
                            ),
                        )
                    append_operation(
                        connection,
                        task_id,
                        "operating_evidence_simulation_calculated",
                        details={
                            "fileId": file_id,
                            "runId": run_id,
                            "evidenceType": evidence_type,
                            "mappingVersion": calculation["mappingVersion"],
                            "status": calculation["status"],
                            "matchedRowCount": calculation["matchedRowCount"],
                            "attentionCount": calculation["attentionCount"],
                            "totalAmountCents": calculation["totalAmountCents"],
                        },
                    )
        except sqlite3.IntegrityError:
            _remove_if_present(final_path)
            raise ValidationError("这份{}资料已经提交过".format(definition["shortLabel"]))
        except Exception:
            _remove_if_present(final_path)
            raise
        return self.get_operating_evidence(task_id)

    def save_manual_resolution(
        self, task_id, file_id, result_type, result_id, payload
    ):
        task_id = clean_text(task_id, "任务编号", 80)
        file_id = clean_text(file_id, "文件版本编号", 80)
        result_type = clean_text(result_type, "结果类型", 40)
        result_id = clean_text(result_id, "结果编号", 120)
        if result_type not in MANUAL_RESULT_TYPES:
            raise ValidationError("这个结果类型不支持人工处理")
        if not isinstance(payload, dict):
            raise ValidationError("人工处理内容格式不正确")
        action_type = clean_text(payload.get("actionType"), "处理方式", 40)
        if action_type not in MANUAL_ACTION_TYPES:
            raise ValidationError("处理方式不支持")
        reason = clean_text(payload.get("reason"), "处理原因", 500)

        with connect(self.database_path) as connection:
            task = _select_task(connection, task_id)
            if task is None:
                raise NotFoundError("没有找到这个对账任务")
            if task["status"] == "completed":
                raise ValidationError("本期已完成，请先填写原因重新打开")
            latest_file = _select_latest_file_id(connection, task_id)
            if latest_file is None or latest_file != file_id:
                raise ValidationError("只能处理当前最新文件版本的结果")
            snapshot = _get_result_snapshot(
                connection, task_id, file_id, result_type, result_id
            )
            if snapshot is None:
                raise NotFoundError("没有找到这条对账结果")

            selected_candidate_key = None
            adjusted_amount_cents = None
            follow_up_date = None
            resolution_state = "resolved"
            if action_type == "select_candidate":
                selected_candidate_key = clean_text(
                    payload.get("selectedCandidateKey"), "候选记录", 160
                )
                valid_keys = {item["key"] for item in snapshot["candidateOptions"]}
                if not valid_keys:
                    raise ValidationError("这条结果没有可人工选择的候选")
                if selected_candidate_key not in valid_keys:
                    raise ValidationError("选择的候选不属于这条结果")
            elif action_type == "adjust_amount":
                adjusted_amount_cents = payload.get("adjustedAmountCents")
                if (
                    isinstance(adjusted_amount_cents, bool)
                    or not isinstance(adjusted_amount_cents, int)
                ):
                    raise ValidationError("请输入人工调整金额，不能默认为0")
                if abs(adjusted_amount_cents) > 10**15:
                    raise ValidationError("人工调整金额超出支持范围")
            elif action_type == "carry_forward":
                follow_up_date = clean_text(
                    payload.get("followUpDate"), "预计处理日期", 10
                )
                try:
                    datetime.strptime(follow_up_date, "%Y-%m-%d")
                except ValueError:
                    raise ValidationError("预计处理日期必须是YYYY-MM-DD")
                resolution_state = "carried_forward"

            previous = connection.execute(
                """
                SELECT id FROM manual_resolution_events
                WHERE task_id = ? AND file_version_id = ?
                  AND result_type = ? AND result_id = ? AND is_current = 1
                """,
                (task_id, file_id, result_type, result_id),
            ).fetchone()
            now = utc_now()
            if previous is not None:
                connection.execute(
                    "UPDATE manual_resolution_events SET is_current = 0 WHERE id = ?",
                    (previous["id"],),
                )
            event_id = "manual-{}".format(uuid.uuid4().hex)
            connection.execute(
                """
                INSERT INTO manual_resolution_events (
                    id, task_id, file_version_id, result_type, result_id,
                    system_status, resolution_state, action_type,
                    selected_candidate_key, adjusted_amount_cents,
                    follow_up_date, reason, previous_event_id, is_current, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    event_id, task_id, file_id, result_type, result_id,
                    snapshot["systemStatus"], resolution_state, action_type,
                    selected_candidate_key, adjusted_amount_cents,
                    follow_up_date, reason,
                    previous["id"] if previous is not None else None,
                    now,
                ),
            )
            summary = _build_completion_summary(connection, task_id)
            next_status = "ready" if summary["canComplete"] else "needs_attention"
            connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (next_status, now, task_id),
            )
            append_operation(
                connection,
                task_id,
                "manual_resolution_saved",
                reason=reason,
                details={
                    "eventId": event_id,
                    "fileVersionId": file_id,
                    "resultType": result_type,
                    "resultId": result_id,
                    "systemStatus": snapshot["systemStatus"],
                    "actionType": action_type,
                    "resolutionState": resolution_state,
                    "selectedCandidateKey": selected_candidate_key,
                    "adjustedAmountCents": adjusted_amount_cents,
                    "followUpDate": follow_up_date,
                    "previousEventId": previous["id"] if previous is not None else None,
                },
            )
            event = connection.execute(
                "SELECT * FROM manual_resolution_events WHERE id = ?",
                (event_id,),
            ).fetchone()
        return {
            "manualResolution": _manual_resolution_to_api(event),
            "completion": self.get_completion_summary(task_id)["completion"],
        }

    def complete_task(self, task_id, payload):
        task_id = clean_text(task_id, "任务编号", 80)
        if not isinstance(payload, dict) or payload.get("confirmed") is not True:
            raise ValidationError("请先确认完成前汇总")
        note = _clean_optional_text(payload.get("note"), "完成说明", 500)
        with connect(self.database_path) as connection:
            task = _select_task(connection, task_id)
            if task is None:
                raise NotFoundError("没有找到这个对账任务")
            if task["status"] == "completed":
                raise ValidationError("本期已经完成")
            summary = _build_completion_summary(connection, task_id)
            if not summary["canComplete"]:
                if summary["unresolvedCount"]:
                    raise ValidationError(
                        "还有{}条必须处理的结果".format(
                            summary["unresolvedCount"]
                        )
                    )
                raise ValidationError("当前文件或对账结果尚未准备完成")
            now = utc_now()
            event_id = "period-{}".format(uuid.uuid4().hex)
            connection.execute(
                """
                INSERT INTO period_lifecycle_events (
                    id, task_id, action, reason, summary_json,
                    rule_version_id, created_at
                ) VALUES (?, ?, 'completed', ?, ?, ?, ?)
                """,
                (
                    event_id, task_id, note,
                    json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                    task["rule_version_id"], now,
                ),
            )
            connection.execute(
                """
                UPDATE tasks
                SET status = 'completed', completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, task_id),
            )
            append_operation(
                connection,
                task_id,
                "period_completed",
                reason=note,
                details={
                    "eventId": event_id,
                    "fileVersionId": summary["latestFileId"],
                    "ruleVersionId": task["rule_version_id"],
                    "resolvedCount": summary["resolvedCount"],
                    "carriedForwardCount": summary["carriedForwardCount"],
                },
            )
        return self.get_task(task_id)

    def reopen_task(self, task_id, payload):
        task_id = clean_text(task_id, "任务编号", 80)
        if not isinstance(payload, dict):
            raise ValidationError("重新打开内容格式不正确")
        reason = clean_text(payload.get("reason"), "重新打开原因", 500)
        with connect(self.database_path) as connection:
            task = _select_task(connection, task_id)
            if task is None:
                raise NotFoundError("没有找到这个对账任务")
            if task["status"] != "completed":
                raise ValidationError("只有已完成的任务才能重新打开")
            summary = _build_completion_summary(connection, task_id)
            now = utc_now()
            event_id = "period-{}".format(uuid.uuid4().hex)
            connection.execute(
                """
                INSERT INTO period_lifecycle_events (
                    id, task_id, action, reason, summary_json,
                    rule_version_id, created_at
                ) VALUES (?, ?, 'reopened', ?, ?, ?, ?)
                """,
                (
                    event_id, task_id, reason,
                    json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                    task["rule_version_id"], now,
                ),
            )
            connection.execute(
                """
                UPDATE tasks
                SET status = 'reopened', reopened_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, task_id),
            )
            append_operation(
                connection,
                task_id,
                "period_reopened",
                reason=reason,
                details={
                    "eventId": event_id,
                    "previousCompletedAt": task["completed_at"],
                },
            )
        return self.get_task(task_id)

    def get_import_records(self, task_id, file_id, sheet_name, page=1, page_size=50):
        task_id = clean_text(task_id, "任务编号", 80)
        file_id = clean_text(file_id, "文件版本编号", 80)
        if sheet_name not in SHEET_VIEWS:
            raise ValidationError("工作表名称不支持")
        try:
            page = int(page)
            page_size = int(page_size)
        except (TypeError, ValueError):
            raise ValidationError("页码必须是整数")
        if page < 1:
            raise ValidationError("页码必须从1开始")
        if page_size not in (20, 50, 100):
            raise ValidationError("每页条数只支持20、50或100")

        with connect(self.database_path) as connection:
            file_row = connection.execute(
                """
                SELECT f.id, d.id AS import_id
                FROM file_versions f
                JOIN data_imports d ON d.file_version_id = f.id
                WHERE f.task_id = ? AND f.id = ?
                """,
                (task_id, file_id),
            ).fetchone()
            if file_row is None:
                raise NotFoundError("没有找到这个文件版本的导入数据")
            return build_record_page(
                connection,
                file_row["import_id"],
                file_row["id"],
                sheet_name,
                page,
                page_size,
            )

    def get_wide_reconciliation_results(
        self, task_id, file_id, status="all", scene="all", query="",
        page=1, page_size=50,
    ):
        task_id = clean_text(task_id, "任务编号", 80)
        file_id = clean_text(file_id, "文件版本编号", 80)
        status, scene, query = _validate_wide_reconciliation_filters(
            status, scene, query
        )
        page, page_size = _validate_pagination(page, page_size)
        with connect(self.database_path) as connection:
            result = build_wide_reconciliation_page(
                connection, task_id, file_id, status, scene, query, page, page_size
            )
        if result is None:
            raise NotFoundError("没有找到这个文件版本的导入数据")
        return result

    def get_reconciliation_results(
        self, task_id, file_id, status="all", page=1, page_size=50
    ):
        task_id = clean_text(task_id, "任务编号", 80)
        file_id = clean_text(file_id, "文件版本编号", 80)
        if status not in ("all", "matched", "needs_attention"):
            raise ValidationError("对账结果筛选条件不支持")
        page, page_size = _validate_pagination(page, page_size)

        with connect(self.database_path) as connection:
            run = connection.execute(
                """
                SELECT rr.id, rr.summary_json
                FROM reconciliation_runs rr
                JOIN file_versions f ON f.id = rr.file_version_id
                WHERE rr.task_id = ? AND rr.file_version_id = ? AND f.task_id = ?
                """,
                (task_id, file_id, task_id),
            ).fetchone()
            if run is None:
                raise NotFoundError("这个文件尚未生成普通结算核对结果")

            filter_sql = ""
            parameters = [run["id"]]
            if status == "matched":
                filter_sql = " AND r.status = 'matched'"
            elif status == "needs_attention":
                filter_sql = " AND r.status != 'matched'"
            total_rows = connection.execute(
                "SELECT COUNT(*) AS count FROM reconciliation_results r WHERE r.run_id = ?{}".format(
                    filter_sql
                ),
                parameters,
            ).fetchone()["count"]
            offset = (page - 1) * page_size
            rows = connection.execute(
                """
                SELECT r.id, r.status, r.primary_identifier,
                       r.settlement_row_number, r.settlement_amount_cents,
                       r.fund_row_number, r.fund_primary_identifier,
                       r.fund_amount_cents, r.difference_cents,
                       r.candidate_count, r.matched_candidate_count,
                       r.explanation, r.suggestion
                FROM reconciliation_results r
                WHERE r.run_id = ?{}
                ORDER BY CASE WHEN r.status = 'matched' THEN 1 ELSE 0 END,
                         r.settlement_row_number
                LIMIT ? OFFSET ?
                """.format(filter_sql),
                (*parameters, page_size, offset),
            ).fetchall()
            manual_map = _manual_resolution_map(
                connection,
                task_id,
                file_id,
                "ordinary_settlement",
                [row["id"] for row in rows],
            )

        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        api_rows = [_reconciliation_result_to_api(row_to_dict(row)) for row in rows]
        for item in api_rows:
            item["manualResolution"] = manual_map.get(item["id"])
        return {
            "fileId": file_id,
            "resultType": "ordinary_settlement",
            "summary": json.loads(run["summary_json"]),
            "filter": status,
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "totalRows": total_rows,
                "totalPages": total_pages,
                "fromRow": offset + 1 if total_rows else 0,
                "toRow": min(offset + page_size, total_rows),
            },
            "rows": api_rows,
        }

    def get_reconciliation_result(self, task_id, file_id, result_id):
        task_id = clean_text(task_id, "任务编号", 80)
        file_id = clean_text(file_id, "文件版本编号", 80)
        result_id = clean_text(result_id, "对账结果编号", 100)
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT r.id, r.status, r.primary_identifier,
                       r.settlement_row_number, r.settlement_amount_cents,
                       r.fund_row_number, r.fund_primary_identifier,
                       r.fund_amount_cents, r.difference_cents,
                       r.candidate_count, r.matched_candidate_count,
                       r.candidate_records_json, r.explanation, r.suggestion,
                       ss.sheet_name AS settlement_sheet_name,
                       ss.primary_identifier AS settlement_primary_identifier,
                       ss.secondary_identifier AS settlement_secondary_identifier,
                       ss.event_time AS settlement_event_time,
                       ss.amount_cents AS settlement_source_amount_cents,
                       ss.raw_values_json AS settlement_raw_values_json,
                       fs.sheet_name AS fund_sheet_name,
                       fs.primary_identifier AS fund_source_primary_identifier,
                       fs.secondary_identifier AS fund_source_secondary_identifier,
                       fs.event_time AS fund_event_time,
                       fs.amount_cents AS fund_source_amount_cents,
                       fs.raw_values_json AS fund_raw_values_json
                FROM reconciliation_results r
                JOIN source_records ss ON ss.id = r.settlement_record_id
                LEFT JOIN source_records fs ON fs.id = r.fund_record_id
                WHERE r.task_id = ? AND r.file_version_id = ? AND r.id = ?
                """,
                (task_id, file_id, result_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("没有找到这条对账结果")
            manual_current, manual_history = _manual_resolution_detail(
                connection, task_id, file_id, "ordinary_settlement", result_id
            )
            snapshot = _get_result_snapshot(
                connection, task_id, file_id, "ordinary_settlement", result_id
            )
        result = _reconciliation_result_to_api(row_to_dict(row))
        result["candidates"] = json.loads(row["candidate_records_json"])
        result["settlementSource"] = {
            "sheetName": row["settlement_sheet_name"],
            "rowNumber": row["settlement_row_number"],
            "primaryIdentifier": row["settlement_primary_identifier"],
            "secondaryIdentifier": row["settlement_secondary_identifier"],
            "eventTime": row["settlement_event_time"],
            "amountCents": row["settlement_source_amount_cents"],
            "values": json.loads(row["settlement_raw_values_json"]),
        }
        result["fundSource"] = None
        if row["fund_sheet_name"]:
            result["fundSource"] = {
                "sheetName": row["fund_sheet_name"],
                "rowNumber": row["fund_row_number"],
                "primaryIdentifier": row["fund_source_primary_identifier"],
                "secondaryIdentifier": row["fund_source_secondary_identifier"],
                "eventTime": row["fund_event_time"],
                "amountCents": row["fund_source_amount_cents"],
                "values": json.loads(row["fund_raw_values_json"]),
            }
        result["candidateOptions"] = snapshot["candidateOptions"]
        result["systemAmountCents"] = snapshot["systemAmountCents"]
        result["manualResolution"] = manual_current
        result["manualHistory"] = manual_history
        return {"result": result}

    def get_refund_reconciliation_results(
        self, task_id, file_id, status="all", page=1, page_size=50
    ):
        task_id = clean_text(task_id, "任务编号", 80)
        file_id = clean_text(file_id, "文件版本编号", 80)
        if status not in ("all", "matched", "needs_attention"):
            raise ValidationError("退款对账结果筛选条件不支持")
        page, page_size = _validate_pagination(page, page_size)

        with connect(self.database_path) as connection:
            run = connection.execute(
                """
                SELECT rr.id, rr.summary_json
                FROM refund_reconciliation_runs rr
                JOIN file_versions f ON f.id = rr.file_version_id
                WHERE rr.task_id = ? AND rr.file_version_id = ? AND f.task_id = ?
                """,
                (task_id, file_id, task_id),
            ).fetchone()
            if run is None:
                raise NotFoundError("这个文件尚未生成退款结算核对结果")

            filter_sql = ""
            if status == "matched":
                filter_sql = " AND r.status = 'matched'"
            elif status == "needs_attention":
                filter_sql = " AND r.status != 'matched'"
            total_rows = connection.execute(
                "SELECT COUNT(*) AS count FROM refund_reconciliation_results r WHERE r.run_id = ?{}".format(
                    filter_sql
                ),
                (run["id"],),
            ).fetchone()["count"]
            offset = (page - 1) * page_size
            rows = connection.execute(
                """
                SELECT r.id, r.status, r.primary_identifier,
                       r.settlement_row_number, r.settlement_amount_cents,
                       r.fund_net_amount_cents, r.difference_cents,
                       r.after_sale_id, r.max_time_difference_seconds,
                       r.candidate_count, r.candidate_group_count,
                       r.matched_candidate_count, r.selected_records_json,
                       r.component_status, r.component_json,
                       r.explanation, r.suggestion
                FROM refund_reconciliation_results r
                WHERE r.run_id = ?{}
                ORDER BY CASE WHEN r.status = 'matched' THEN 1 ELSE 0 END,
                         r.settlement_row_number
                LIMIT ? OFFSET ?
                """.format(filter_sql),
                (run["id"], page_size, offset),
            ).fetchall()
            manual_map = _manual_resolution_map(
                connection,
                task_id,
                file_id,
                "refund_settlement",
                [row["id"] for row in rows],
            )

        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        api_rows = [_refund_reconciliation_result_to_api(row_to_dict(row)) for row in rows]
        for item in api_rows:
            item["manualResolution"] = manual_map.get(item["id"])
        return {
            "fileId": file_id,
            "resultType": "refund_settlement",
            "summary": json.loads(run["summary_json"]),
            "filter": status,
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "totalRows": total_rows,
                "totalPages": total_pages,
                "fromRow": offset + 1 if total_rows else 0,
                "toRow": min(offset + page_size, total_rows),
            },
            "rows": api_rows,
        }

    def get_refund_reconciliation_result(self, task_id, file_id, result_id):
        task_id = clean_text(task_id, "任务编号", 80)
        file_id = clean_text(file_id, "文件版本编号", 80)
        result_id = clean_text(result_id, "退款对账结果编号", 100)
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT r.id, r.status, r.primary_identifier,
                       r.settlement_row_number, r.settlement_amount_cents,
                       r.fund_net_amount_cents, r.difference_cents,
                       r.after_sale_id, r.max_time_difference_seconds,
                       r.candidate_count, r.candidate_group_count,
                       r.matched_candidate_count, r.selected_records_json,
                       r.candidate_groups_json, r.component_status,
                       r.component_json, r.explanation, r.suggestion,
                       ss.sheet_name AS settlement_sheet_name,
                       ss.primary_identifier AS settlement_primary_identifier,
                       ss.secondary_identifier AS settlement_secondary_identifier,
                       ss.event_time AS settlement_event_time,
                       ss.amount_cents AS settlement_source_amount_cents,
                       ss.raw_values_json AS settlement_raw_values_json
                FROM refund_reconciliation_results r
                JOIN source_records ss ON ss.id = r.settlement_record_id
                WHERE r.task_id = ? AND r.file_version_id = ? AND r.id = ?
                """,
                (task_id, file_id, result_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("没有找到这条退款对账结果")
            selected_records = json.loads(row["selected_records_json"])
            selected_ids = [item.get("sourceRecordId") for item in selected_records if item.get("sourceRecordId")]
            source_rows = []
            if selected_ids:
                placeholders = ",".join("?" for _ in selected_ids)
                source_rows = connection.execute(
                    """
                    SELECT id, sheet_name, row_number, primary_identifier,
                           secondary_identifier, event_time, amount_cents, raw_values_json
                    FROM source_records
                    WHERE id IN ({})
                    """.format(placeholders),
                    selected_ids,
                ).fetchall()
            manual_current, manual_history = _manual_resolution_detail(
                connection, task_id, file_id, "refund_settlement", result_id
            )
            snapshot = _get_result_snapshot(
                connection, task_id, file_id, "refund_settlement", result_id
            )

        result = _refund_reconciliation_result_to_api(row_to_dict(row))
        result["candidateGroups"] = json.loads(row["candidate_groups_json"])
        result["settlementSource"] = {
            "sheetName": row["settlement_sheet_name"],
            "rowNumber": row["settlement_row_number"],
            "primaryIdentifier": row["settlement_primary_identifier"],
            "secondaryIdentifier": row["settlement_secondary_identifier"],
            "eventTime": row["settlement_event_time"],
            "amountCents": row["settlement_source_amount_cents"],
            "values": json.loads(row["settlement_raw_values_json"]),
        }
        source_by_id = {item["id"]: _source_record_to_api(item) for item in source_rows}
        result["fundSources"] = [
            source_by_id[item["sourceRecordId"]]
            for item in selected_records
            if item.get("sourceRecordId") in source_by_id
        ]
        result["candidateOptions"] = snapshot["candidateOptions"]
        result["systemAmountCents"] = snapshot["systemAmountCents"]
        result["manualResolution"] = manual_current
        result["manualHistory"] = manual_history
        return {"result": result}

    def get_supplementary_results(
        self, task_id, file_id, result_type, status="all", page=1, page_size=50
    ):
        task_id = clean_text(task_id, "任务编号", 80)
        file_id = clean_text(file_id, "文件版本编号", 80)
        if result_type not in SUPPLEMENTARY_RESULT_TYPES:
            raise ValidationError("补充核对结果类型不支持")
        page, page_size = _validate_pagination(page, page_size)
        allowed_statuses = _supplementary_statuses(result_type)
        if status not in {"all", "cleared", "needs_attention", *allowed_statuses}:
            raise ValidationError("补充核对结果筛选条件不支持")

        with connect(self.database_path) as connection:
            run = connection.execute(
                """
                SELECT srr.id, srr.summary_json
                FROM supplementary_reconciliation_runs srr
                JOIN file_versions f ON f.id = srr.file_version_id
                WHERE srr.task_id = ? AND srr.file_version_id = ?
                  AND f.task_id = ? AND srr.is_current = 1
                """,
                (task_id, file_id, task_id),
            ).fetchone()
            if run is None:
                raise NotFoundError("这个文件尚未生成跨月、售后、成本和其他收支结果")

            filter_sql, filter_parameters = _supplementary_filter_sql(result_type, status)
            parameters = [run["id"], result_type, *filter_parameters]
            total_rows = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM supplementary_reconciliation_results r
                WHERE r.run_id = ? AND r.result_type = ?{}
                """.format(filter_sql),
                parameters,
            ).fetchone()["count"]
            offset = (page - 1) * page_size
            rows = connection.execute(
                """
                SELECT r.id, r.result_type, r.status, r.primary_identifier,
                       r.source_row_number, r.linked_row_number,
                       r.amount_cents, r.calculated_amount_cents,
                       r.group_key, r.metadata_json, r.explanation, r.suggestion
                FROM supplementary_reconciliation_results r
                WHERE r.run_id = ? AND r.result_type = ?{}
                ORDER BY CASE WHEN r.status IN ({}) THEN 0 ELSE 1 END,
                         r.source_row_number, r.id
                LIMIT ? OFFSET ?
                """.format(
                    filter_sql,
                    ",".join("?" for _ in SUPPLEMENTARY_RESULT_TYPES[result_type]["attention"])
                    or "''",
                ),
                (
                    *parameters,
                    *sorted(SUPPLEMENTARY_RESULT_TYPES[result_type]["attention"]),
                    page_size,
                    offset,
                ),
            ).fetchall()
            manual_map = _manual_resolution_map(
                connection,
                task_id,
                file_id,
                result_type,
                [row["id"] for row in rows],
            )

        summary = json.loads(run["summary_json"])
        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        api_rows = [_supplementary_result_to_api(row_to_dict(row)) for row in rows]
        for item in api_rows:
            item["manualResolution"] = manual_map.get(item["id"])
        return {
            "fileId": file_id,
            "resultType": result_type,
            "summary": summary[SUPPLEMENTARY_RESULT_TYPES[result_type]["summaryKey"]],
            "filter": status,
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "totalRows": total_rows,
                "totalPages": total_pages,
                "fromRow": offset + 1 if total_rows else 0,
                "toRow": min(offset + page_size, total_rows),
            },
            "rows": api_rows,
        }

    def get_supplementary_result(self, task_id, file_id, result_type, result_id):
        task_id = clean_text(task_id, "任务编号", 80)
        file_id = clean_text(file_id, "文件版本编号", 80)
        result_id = clean_text(result_id, "补充核对结果编号", 120)
        if result_type not in SUPPLEMENTARY_RESULT_TYPES:
            raise ValidationError("补充核对结果类型不支持")
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT r.id, r.result_type, r.status, r.primary_identifier,
                       r.source_row_number, r.linked_row_number,
                       r.amount_cents, r.calculated_amount_cents,
                       r.group_key, r.metadata_json, r.explanation, r.suggestion,
                       r.source_record_id, r.linked_source_record_id
                FROM supplementary_reconciliation_results r
                JOIN supplementary_reconciliation_runs srr ON srr.id = r.run_id
                WHERE r.task_id = ? AND r.file_version_id = ?
                  AND r.result_type = ? AND r.id = ? AND srr.is_current = 1
                """,
                (task_id, file_id, result_type, result_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("没有找到这条补充核对结果")
            source_ids = [row["source_record_id"]]
            if row["linked_source_record_id"]:
                source_ids.append(row["linked_source_record_id"])
            placeholders = ",".join("?" for _ in source_ids)
            sources = connection.execute(
                """
                SELECT sr.id, sr.task_id, sr.file_version_id, sr.sheet_name,
                       sr.row_number, sr.primary_identifier, sr.secondary_identifier,
                       sr.event_time, sr.amount_cents, sr.raw_values_json,
                       t.period AS task_period
                FROM source_records sr
                JOIN tasks t ON t.id = sr.task_id
                WHERE sr.id IN ({})
                """.format(placeholders),
                source_ids,
            ).fetchall()
            manual_current, manual_history = _manual_resolution_detail(
                connection, task_id, file_id, result_type, result_id
            )
            snapshot = _get_result_snapshot(
                connection, task_id, file_id, result_type, result_id
            )
        result = _supplementary_result_to_api(row_to_dict(row))
        source_by_id = {
            item["id"]: _source_record_with_context_to_api(item) for item in sources
        }
        result["source"] = source_by_id.get(row["source_record_id"])
        result["linkedSource"] = source_by_id.get(row["linked_source_record_id"])
        result["candidateOptions"] = snapshot["candidateOptions"]
        result["systemAmountCents"] = snapshot["systemAmountCents"]
        result["manualResolution"] = manual_current
        result["manualHistory"] = manual_history
        return {"result": result}

    def export_results(
        self, task_id, file_id, result_type, status="all", scene="all", query=""
    ):
        task_id = clean_text(task_id, "任务编号", 80)
        file_id = clean_text(file_id, "文件版本编号", 80)
        result_type = clean_text(result_type, "结果类型", 40)
        status = clean_text(status, "筛选条件", 40)
        if result_type not in RESULT_TYPE_LABELS:
            raise ValidationError("导出结果类型不支持")
        if result_type == "wide_reconciliation":
            status, scene, query = _validate_wide_reconciliation_filters(
                status, scene, query
            )
            with connect(self.database_path) as connection:
                first_page = build_wide_reconciliation_page(
                    connection,
                    task_id,
                    file_id,
                    status,
                    scene,
                    query,
                    1,
                    MAX_WIDE_EXPORT_ROWS,
                )
            if first_page is None:
                raise NotFoundError("没有找到这个文件版本的导入数据")
            if first_page["pagination"]["totalRows"] > MAX_WIDE_EXPORT_ROWS:
                raise ValidationError(
                    "当前筛选超过{:,}行，请按业务场景或编号缩小范围后导出".format(
                        MAX_WIDE_EXPORT_ROWS
                    )
                )
            rows = list(first_page["rows"])
        else:
            first_page = self._get_export_result_page(
                task_id, file_id, result_type, status, 1
            )
            rows = list(first_page["rows"])
            for page in range(2, first_page["pagination"]["totalPages"] + 1):
                rows.extend(
                    self._get_export_result_page(
                        task_id, file_id, result_type, status, page
                    )["rows"]
                )

        detail = self.get_task(task_id)
        file_version = next(
            (item for item in detail["files"] if item["id"] == file_id), None
        )
        if file_version is None:
            raise NotFoundError("没有找到这个文件版本")
        if result_type == "wide_reconciliation":
            exported = build_wide_reconciliation_export(
                detail["task"], file_version, status, scene, query, rows
            )
        else:
            exported = build_result_export(
                detail["task"], file_version, result_type, status, rows
            )
        operation_details = {
            "fileVersionId": file_id,
            "resultType": result_type,
            "filter": status,
            "rowCount": exported["rowCount"],
            "fileName": exported["fileName"],
        }
        if result_type == "wide_reconciliation":
            operation_details.update({"scene": scene, "query": query})
        with connect(self.database_path) as connection:
            append_operation(
                connection,
                task_id,
                "results_exported",
                details=operation_details,
            )
        return exported

    def _get_export_result_page(
        self, task_id, file_id, result_type, status, page
    ):
        if result_type == "ordinary_settlement":
            return self.get_reconciliation_results(
                task_id, file_id, status, page, 100
            )
        if result_type == "refund_settlement":
            return self.get_refund_reconciliation_results(
                task_id, file_id, status, page, 100
            )
        return self.get_supplementary_results(
            task_id, file_id, result_type, status, page, 100
        )

    def get_platform_balance(self, task_id):
        task_id = clean_text(task_id, "任务编号", 80)
        with connect(self.database_path) as connection:
            if _select_task(connection, task_id) is None:
                raise NotFoundError("没有找到这个对账任务")
            snapshot = _select_platform_balance_snapshot(connection, task_id)
        return {"platformBalance": _platform_balance_snapshot_to_api(snapshot)}

    def get_platform_balance_results(
        self, task_id, status="all", page=1, page_size=50
    ):
        task_id = clean_text(task_id, "任务编号", 80)
        status = clean_text(status, "筛选条件", 40)
        if status not in ("all", "attention", "matched"):
            raise ValidationError("平台账户完整性筛选条件不支持")
        page, page_size = _validate_pagination(page, page_size)
        with connect(self.database_path) as connection:
            snapshot = _select_platform_balance_snapshot(connection, task_id)
            if snapshot is None or snapshot.get("run_id") is None:
                raise NotFoundError("当前任务还没有可查看的平台账户完整性结果")
            where = ""
            parameters = [snapshot["run_id"]]
            if status == "matched":
                where = " AND r.status = 'matched'"
            elif status == "attention":
                where = " AND r.status != 'matched'"
            total_rows = connection.execute(
                "SELECT COUNT(*) AS count FROM platform_balance_results r WHERE r.run_id = ?{}".format(where),
                parameters,
            ).fetchone()["count"]
            offset = (page - 1) * page_size
            rows = connection.execute(
                """
                SELECT r.*, s.raw_values_json
                FROM platform_balance_results r
                LEFT JOIN platform_balance_source_rows s
                  ON s.file_id = r.file_id
                 AND s.sheet_name = r.source_sheet
                 AND s.row_number = r.source_row_number
                WHERE r.run_id = ?{}
                ORDER BY CASE r.status WHEN 'matched' THEN 1 ELSE 0 END,
                         CASE r.level WHEN 'day' THEN 0 WHEN 'month' THEN 1 ELSE 2 END,
                         r.period_key, r.source_row_number
                LIMIT ? OFFSET ?
                """.format(where),
                (*parameters, page_size, offset),
            ).fetchall()
        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        return {
            "summary": json.loads(snapshot["run_summary_json"] or "{}"),
            "file": _platform_balance_snapshot_to_api(snapshot)["latestFile"],
            "rows": [_platform_balance_result_to_api(row) for row in rows],
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "totalRows": total_rows,
                "totalPages": total_pages,
                "fromRow": offset + 1 if total_rows else 0,
                "toRow": min(offset + page_size, total_rows),
            },
            "filter": status,
        }

    def upload_platform_balance_workbook(
        self, task_id, original_name, content, replacement_reason=None
    ):
        task_id = clean_text(task_id, "任务编号", 80)
        file_name = _validate_file_name(original_name)
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise ValidationError("请选择平台账户汇总Excel")
        if len(content) > MAX_WORKBOOK_BYTES:
            raise ValidationError("Excel文件不能超过50MB")
        reason = _clean_optional_text(replacement_reason, "替换原因", 300)
        digest = hashlib.sha256(content).hexdigest()
        with connect(self.database_path) as connection:
            task = _select_task(connection, task_id)
            if task is None:
                raise NotFoundError("没有找到这个对账任务")
            if task["status"] == "completed":
                raise ValidationError("本期已完成，请先填写原因重新打开")
            duplicate = connection.execute(
                "SELECT 1 FROM platform_balance_files WHERE task_id = ? AND content_sha256 = ?",
                (task_id, digest),
            ).fetchone()
            if duplicate is not None:
                raise ValidationError("这个平台账户汇总文件已经导入过")
            previous = connection.execute(
                "SELECT 1 FROM platform_balance_files WHERE task_id = ? LIMIT 1",
                (task_id,),
            ).fetchone()
        if previous is not None and reason is None:
            raise ValidationError("重新导入平台账户汇总时请填写替换说明")

        file_id = "balance-file-{}".format(uuid.uuid4().hex)
        task_directory = self.upload_dir / task_id / "platform-balance"
        task_directory.mkdir(parents=True, exist_ok=True)
        temporary_path = task_directory / ".{}.uploading".format(file_id)
        final_path = task_directory / "{}.xlsx".format(file_id)
        stored_name = "{}/platform-balance/{}.xlsx".format(task_id, file_id)
        try:
            with temporary_path.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            inspection = inspect_platform_balance_workbook(temporary_path)
            calculation = None
            if inspection["status"] == "passed":
                calculation = calculate_platform_balance(
                    temporary_path, task["period"], task["tolerance_cents"]
                )
            os.replace(str(temporary_path), str(final_path))
        except WorkbookInspectionError as exc:
            _remove_if_present(temporary_path)
            raise ValidationError(str(exc))
        except Exception:
            _remove_if_present(temporary_path)
            raise

        now = utc_now()
        try:
            with connect(self.database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO platform_balance_files (
                        id, task_id, original_name, stored_name, content_sha256,
                        size_bytes, replacement_reason, mapping_version,
                        is_simulated_mapping, inspection_status, inspection_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        file_id, task_id, file_name, stored_name, digest, len(content),
                        reason, PLATFORM_BALANCE_MAPPING_VERSION, inspection["status"],
                        json.dumps(inspection, ensure_ascii=False, separators=(",", ":")),
                        now,
                    ),
                )
                run_id = None
                if calculation is not None:
                    connection.execute(
                        """
                        UPDATE platform_balance_runs
                        SET is_current = 0, superseded_at = ?
                        WHERE task_id = ? AND is_current = 1
                        """,
                        (now, task_id),
                    )
                    run_id = "balance-run-{}".format(uuid.uuid4().hex)
                    summary = {
                        key: value for key, value in calculation.items()
                        if key not in ("sourceRows", "results")
                    }
                    connection.execute(
                        """
                        INSERT INTO platform_balance_runs (
                            id, file_id, task_id, rule_version_id, mapping_version,
                            enforcement_mode, status, tolerance_cents,
                            total_result_count, matched_count, attention_count,
                            summary_json, is_current, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                        """,
                        (
                            run_id, file_id, task_id, task["rule_version_id"],
                            calculation["mappingVersion"], calculation["enforcementMode"],
                            calculation["status"], calculation["toleranceCents"],
                            calculation["totalResultCount"], calculation["matchedCount"],
                            calculation["attentionCount"],
                            json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                            now,
                        ),
                    )
                    connection.executemany(
                        """
                        INSERT INTO platform_balance_source_rows (
                            file_id, task_id, sheet_name, row_number, record_type,
                            raw_values_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                file_id, task_id, item["sheetName"], item["rowNumber"],
                                item["recordType"], item["rawValuesJson"], now,
                            )
                            for item in calculation["sourceRows"]
                        ],
                    )
                    connection.executemany(
                        """
                        INSERT INTO platform_balance_results (
                            id, run_id, file_id, task_id, level, status, batch_key,
                            account, period_key, source_sheet, source_row_number,
                            summary_count, detail_count, summary_income_cents,
                            detail_income_cents, summary_expense_cents,
                            detail_expense_cents, opening_balance_cents,
                            closing_balance_cents, calculated_closing_balance_cents,
                            difference_cents, metadata_json, explanation, suggestion,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                "balance-result-{}".format(uuid.uuid4().hex), run_id,
                                file_id, task_id, item["level"], item["status"],
                                item.get("batchKey"), item.get("account"), item.get("periodKey"),
                                item["sourceSheet"], item["sourceRowNumber"],
                                item.get("summaryCount"), item.get("detailCount"),
                                item.get("summaryIncomeCents"), item.get("detailIncomeCents"),
                                item.get("summaryExpenseCents"), item.get("detailExpenseCents"),
                                item.get("openingBalanceCents"), item.get("closingBalanceCents"),
                                item.get("calculatedClosingBalanceCents"), item.get("differenceCents"),
                                json.dumps(item.get("metadata") or {}, ensure_ascii=False, separators=(",", ":")),
                                item["explanation"], item["suggestion"], now,
                            )
                            for item in calculation["results"]
                        ],
                    )
                append_operation(
                    connection,
                    task_id,
                    "platform_balance_uploaded",
                    reason=reason,
                    details={
                        "fileId": file_id,
                        "runId": run_id,
                        "originalName": file_name,
                        "contentSha256": digest,
                        "inspectionStatus": inspection["status"],
                        "mappingVersion": PLATFORM_BALANCE_MAPPING_VERSION,
                        "trialMode": True,
                        "attentionCount": calculation["attentionCount"] if calculation else None,
                    },
                )
        except sqlite3.IntegrityError:
            _remove_if_present(final_path)
            raise ValidationError("这个平台账户汇总文件已经导入过")
        except Exception:
            _remove_if_present(final_path)
            raise
        return self.get_platform_balance(task_id)

    def get_pending_settlement(self, task_id):
        task_id = clean_text(task_id, "任务编号", 80)
        with connect(self.database_path) as connection:
            if _select_task(connection, task_id) is None:
                raise NotFoundError("没有找到这个对账任务")
            snapshot = _select_pending_settlement_snapshot(connection, task_id)
        return {"pendingSettlement": _pending_settlement_snapshot_to_api(snapshot)}

    def get_pending_settlement_results(
        self, task_id, status="all", page=1, page_size=50
    ):
        task_id = clean_text(task_id, "任务编号", 80)
        status = clean_text(status, "筛选条件", 40)
        if status not in ("all", "attention", "waiting", "overdue", "excluded"):
            raise ValidationError("待结算跟踪筛选条件不支持")
        page, page_size = _validate_pagination(page, page_size)
        with connect(self.database_path) as connection:
            snapshot = _select_pending_settlement_snapshot(connection, task_id)
            if snapshot is None or snapshot.get("run_id") is None:
                raise NotFoundError("当前任务还没有可查看的待结算跟踪结果")
            where = ""
            parameters = [snapshot["run_id"]]
            if status == "attention":
                placeholders = ",".join("?" for _ in PENDING_SETTLEMENT_ATTENTION_STATUSES)
                where = " AND r.status IN ({})".format(placeholders)
                parameters.extend(sorted(PENDING_SETTLEMENT_ATTENTION_STATUSES))
            elif status in ("waiting", "overdue"):
                where = " AND r.status = ?"
                parameters.append(status)
            elif status == "excluded":
                where = " AND r.status IN ('canceled_refunded', 'settled_excluded')"
            total_rows = connection.execute(
                "SELECT COUNT(*) AS count FROM pending_settlement_results r WHERE r.run_id = ?{}".format(where),
                parameters,
            ).fetchone()["count"]
            offset = (page - 1) * page_size
            rows = connection.execute(
                """
                SELECT r.*, s.raw_values_json,
                       a.raw_values_json AS aux_raw_values_json
                FROM pending_settlement_results r
                LEFT JOIN pending_settlement_source_rows s
                  ON s.file_id = r.file_id
                 AND s.sheet_name = r.source_sheet
                 AND s.row_number = r.source_row_number
                LEFT JOIN pending_settlement_source_rows a
                  ON a.file_id = r.file_id
                 AND a.sheet_name = r.aux_source_sheet
                 AND a.row_number = r.aux_source_row_number
                WHERE r.run_id = ?{}
                ORDER BY
                    CASE r.status
                        WHEN 'overdue' THEN 0
                        WHEN 'restricted' THEN 1
                        WHEN 'after_sales' THEN 2
                        WHEN 'insufficient' THEN 3
                        WHEN 'source_anomaly' THEN 4
                        WHEN 'invalid_source' THEN 5
                        WHEN 'waiting' THEN 6
                        ELSE 7
                    END,
                    r.scene_code, r.source_row_number
                LIMIT ? OFFSET ?
                """.format(where),
                (*parameters, page_size, offset),
            ).fetchall()
        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        return {
            "summary": json.loads(snapshot["run_summary_json"] or "{}"),
            "file": _pending_settlement_snapshot_to_api(snapshot)["latestFile"],
            "rows": [_pending_settlement_result_to_api(row) for row in rows],
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "totalRows": total_rows,
                "totalPages": total_pages,
                "fromRow": offset + 1 if total_rows else 0,
                "toRow": min(offset + page_size, total_rows),
            },
            "filter": status,
        }

    def upload_pending_settlement_workbook(
        self, task_id, original_name, content, replacement_reason=None
    ):
        task_id = clean_text(task_id, "任务编号", 80)
        file_name = _validate_file_name(original_name)
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise ValidationError("请选择待结算订单Excel")
        if len(content) > MAX_WORKBOOK_BYTES:
            raise ValidationError("Excel文件不能超过50MB")
        reason = _clean_optional_text(replacement_reason, "替换原因", 300)
        digest = hashlib.sha256(content).hexdigest()
        with connect(self.database_path) as connection:
            task = _select_task(connection, task_id)
            if task is None:
                raise NotFoundError("没有找到这个对账任务")
            if task["status"] == "completed":
                raise ValidationError("本期已完成，请先填写原因重新打开")
            duplicate = connection.execute(
                "SELECT 1 FROM pending_settlement_files WHERE task_id = ? AND content_sha256 = ?",
                (task_id, digest),
            ).fetchone()
            if duplicate is not None:
                raise ValidationError("这个待结算订单文件已经导入过")
            previous = connection.execute(
                "SELECT 1 FROM pending_settlement_files WHERE task_id = ? LIMIT 1",
                (task_id,),
            ).fetchone()
        if previous is not None and reason is None:
            raise ValidationError("重新导入待结算订单时请填写替换说明")

        file_id = "pending-file-{}".format(uuid.uuid4().hex)
        task_directory = self.upload_dir / task_id / "pending-settlement"
        task_directory.mkdir(parents=True, exist_ok=True)
        temporary_path = task_directory / ".{}.uploading".format(file_id)
        final_path = task_directory / "{}.xlsx".format(file_id)
        stored_name = "{}/pending-settlement/{}.xlsx".format(task_id, file_id)
        try:
            with temporary_path.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            inspection = inspect_pending_settlement_workbook(temporary_path)
            calculation = None
            if inspection["status"] == "passed":
                calculation = calculate_pending_settlement(
                    temporary_path,
                    task["period"],
                    task["settlement_wait_days"],
                )
            os.replace(str(temporary_path), str(final_path))
        except WorkbookInspectionError as exc:
            _remove_if_present(temporary_path)
            raise ValidationError(str(exc))
        except Exception:
            _remove_if_present(temporary_path)
            raise

        now = utc_now()
        try:
            with connect(self.database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO pending_settlement_files (
                        id, task_id, original_name, stored_name, content_sha256,
                        size_bytes, replacement_reason, mapping_version,
                        is_simulated_mapping, inspection_status, inspection_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        file_id, task_id, file_name, stored_name, digest, len(content),
                        reason, PENDING_SETTLEMENT_MAPPING_VERSION, inspection["status"],
                        json.dumps(inspection, ensure_ascii=False, separators=(",", ":")),
                        now,
                    ),
                )
                run_id = None
                if calculation is not None:
                    connection.execute(
                        """
                        UPDATE pending_settlement_runs
                        SET is_current = 0, superseded_at = ?
                        WHERE task_id = ? AND is_current = 1
                        """,
                        (now, task_id),
                    )
                    run_id = "pending-run-{}".format(uuid.uuid4().hex)
                    summary = {
                        key: value for key, value in calculation.items()
                        if key not in ("sourceRows", "results")
                    }
                    connection.execute(
                        """
                        INSERT INTO pending_settlement_runs (
                            id, file_id, task_id, rule_version_id, mapping_version,
                            enforcement_mode, status, as_of, wait_days,
                            total_result_count, attention_count, waiting_count,
                            overdue_count, excluded_count, pending_amount_cents,
                            summary_json, is_current, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                        """,
                        (
                            run_id, file_id, task_id, task["rule_version_id"],
                            calculation["mappingVersion"], calculation["enforcementMode"],
                            calculation["status"], calculation["asOf"], calculation["waitDays"],
                            calculation["totalResultCount"], calculation["attentionCount"],
                            calculation["waitingCount"], calculation["overdueCount"],
                            calculation["excludedCount"], calculation["pendingAmountCents"],
                            json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                            now,
                        ),
                    )
                    connection.executemany(
                        """
                        INSERT INTO pending_settlement_source_rows (
                            file_id, task_id, sheet_name, row_number, record_type,
                            raw_values_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                file_id, task_id, item["sheetName"], item["rowNumber"],
                                item["recordType"], item["rawValuesJson"], now,
                            )
                            for item in calculation["sourceRows"]
                        ],
                    )
                    connection.executemany(
                        """
                        INSERT INTO pending_settlement_results (
                            id, run_id, file_id, task_id, status, scene_code,
                            order_id, suborder_id, product_id, payment_cents,
                            order_status, settlement_status, settlement_cycle,
                            expected_settlement_at, expected_settlement_cents,
                            completed_at, after_sales_status, restriction_status,
                            entered_settlement, recheck_at, completion_condition,
                            source_type, source_sheet, source_row_number,
                            aux_source_sheet, aux_source_row_number, metadata_json,
                            explanation, suggestion, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                "pending-result-{}".format(uuid.uuid4().hex), run_id,
                                file_id, task_id, item["status"], item["sceneCode"],
                                item.get("orderId"), item.get("suborderId"), item.get("productId"),
                                item.get("paymentCents"), item.get("orderStatus"),
                                item.get("settlementStatus"), item.get("settlementCycle"),
                                item.get("expectedSettlementAt"), item.get("expectedSettlementCents"),
                                item.get("completedAt"), item.get("afterSalesStatus"),
                                item.get("restrictionStatus"), item.get("enteredSettlement"),
                                item.get("recheckAt"), item["completionCondition"],
                                item["sourceType"], item["sourceSheet"], item["sourceRowNumber"],
                                item.get("auxSourceSheet"), item.get("auxSourceRowNumber"),
                                json.dumps(item.get("metadata") or {}, ensure_ascii=False, separators=(",", ":")),
                                item["explanation"], item["suggestion"], now,
                            )
                            for item in calculation["results"]
                        ],
                    )
                append_operation(
                    connection,
                    task_id,
                    "pending_settlement_uploaded",
                    reason=reason,
                    details={
                        "fileId": file_id,
                        "runId": run_id,
                        "originalName": file_name,
                        "contentSha256": digest,
                        "inspectionStatus": inspection["status"],
                        "mappingVersion": PENDING_SETTLEMENT_MAPPING_VERSION,
                        "trialMode": True,
                        "attentionCount": calculation["attentionCount"] if calculation else None,
                    },
                )
        except sqlite3.IntegrityError:
            _remove_if_present(final_path)
            raise ValidationError("这个待结算订单文件已经导入过")
        except Exception:
            _remove_if_present(final_path)
            raise
        return self.get_pending_settlement(task_id)

    def upload_workbook(self, task_id, original_name, content, replacement_reason=None):
        task_id = clean_text(task_id, "任务编号", 80)
        file_name = _validate_file_name(original_name)
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise ValidationError("请选择要导入的Excel文件")
        if len(content) > MAX_WORKBOOK_BYTES:
            raise ValidationError("Excel文件不能超过50MB")
        reason = _clean_optional_text(replacement_reason, "替换原因", 300)
        digest = hashlib.sha256(content).hexdigest()

        with connect(self.database_path) as connection:
            task = _select_task(connection, task_id)
            if task is None:
                raise NotFoundError("没有找到这个对账任务")
            if task["status"] == "completed":
                raise ValidationError("本期已完成，请先填写原因重新打开")
            duplicate = _select_file_by_digest(connection, task_id, digest)
            if duplicate is not None:
                raise DuplicateFileError(
                    _file_to_api(row_to_dict(duplicate), self.database_path)
                )
            previous_file = connection.execute(
                "SELECT 1 FROM file_versions WHERE task_id = ? LIMIT 1", (task_id,)
            ).fetchone()
            template = _load_bill_template(connection, status="current")
            if template is None:
                raise RuntimeError("没有可用的账单模板")
            template_definitions = _bill_template_definitions(template)
        if previous_file is not None and reason is None:
            raise ValidationError("重新导入时请填写重传说明")

        file_id = "file-{}".format(uuid.uuid4().hex)
        task_directory = self.upload_dir / task_id
        task_directory.mkdir(parents=True, exist_ok=True)
        temporary_path = task_directory / ".{}.uploading".format(file_id)
        final_path = task_directory / "{}.xlsx".format(file_id)
        stored_name = "{}/{}.xlsx".format(task_id, file_id)

        try:
            with temporary_path.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            inspection = inspect_workbook(temporary_path, template_definitions)
            inspection["templateVersionId"] = template["id"]
            inspection["templateVersionLabel"] = template["version_label"]
            data_import = None
            amount_checks = None
            ordinary_reconciliation = None
            refund_reconciliation = None
            supplementary_reconciliation = None
            if inspection["status"] == "passed":
                data_import = analyze_workbook_data(
                    temporary_path, task["period"], template_definitions
                )
            os.replace(str(temporary_path), str(final_path))
        except WorkbookInspectionError as exc:
            _remove_if_present(temporary_path)
            raise ValidationError(str(exc))
        except Exception:
            _remove_if_present(temporary_path)
            raise

        now = utc_now()
        task_status = "ready"
        if inspection["status"] != "passed" or (
            data_import is not None and data_import["status"] == "failed"
        ):
            task_status = "needs_attention"
        try:
            with connect(self.database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO file_versions (
                        id, task_id, original_name, stored_name, content_sha256,
                        size_bytes, replacement_reason, created_at, template_version_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_id,
                        task_id,
                        file_name,
                        stored_name,
                        digest,
                        len(content),
                        reason,
                        now,
                        template["id"],
                    ),
                )
                if data_import is not None:
                    mapped_records, mapping_summary = _apply_platform_value_mappings(
                        connection, task_id, file_id, data_import["records"], now
                    )
                    data_import = {
                        **data_import,
                        "records": mapped_records,
                        "mappingSummary": mapping_summary,
                    }
                    import_id = self._insert_data_import(
                        connection, task_id, file_id, data_import, now
                    )
                    if data_import["status"] != "failed":
                        amount_checks = calculate_amount_checks(
                            data_import["records"], task["tolerance_cents"]
                        )
                        self._insert_amount_checks(
                            connection,
                            task_id,
                            file_id,
                            import_id,
                            task["rule_version_id"],
                            amount_checks,
                            now,
                        )
                        if amount_checks["status"] == "failed":
                            task_status = "needs_attention"
                        ordinary_reconciliation = calculate_ordinary_settlement_reconciliation(
                            data_import["records"], task["tolerance_cents"]
                        )
                        self._insert_reconciliation(
                            connection,
                            task_id,
                            file_id,
                            import_id,
                            task["rule_version_id"],
                            ordinary_reconciliation,
                            now,
                        )
                        if ordinary_reconciliation["status"] == "needs_attention":
                            task_status = "needs_attention"
                        refund_reconciliation = calculate_refund_settlement_reconciliation(
                            data_import["records"],
                            task["tolerance_cents"],
                            task["refund_auto_group_seconds"],
                            task["refund_candidate_seconds"],
                        )
                        self._insert_refund_reconciliation(
                            connection,
                            task_id,
                            file_id,
                            import_id,
                            task["rule_version_id"],
                            refund_reconciliation,
                            now,
                        )
                        if refund_reconciliation["status"] == "needs_attention":
                            task_status = "needs_attention"
                        stored_records = _load_import_records(connection, import_id)
                        historical_orders = _load_historical_order_records(
                            connection, task_id, import_id
                        )
                        supplementary_reconciliation = calculate_supplementary_reconciliation(
                            stored_records,
                            historical_orders,
                            task["settlement_wait_days"],
                            task_period=task["period"],
                            tolerance_cents=task["tolerance_cents"],
                        )
                        self._insert_supplementary_reconciliation(
                            connection,
                            task_id,
                            file_id,
                            import_id,
                            task["rule_version_id"],
                            supplementary_reconciliation,
                            historical_orders,
                            now,
                        )
                        if supplementary_reconciliation["status"] == "needs_attention":
                            task_status = "needs_attention"
                connection.execute(
                    """
                    INSERT INTO workbook_inspections (
                        id, file_version_id, status, sheet_count, required_sheet_count,
                        found_required_sheet_count, summary_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "inspection-{}".format(uuid.uuid4().hex),
                        file_id,
                        inspection["status"],
                        inspection["sheetCount"],
                        inspection["requiredSheetCount"],
                        inspection["foundRequiredSheetCount"],
                        json.dumps(inspection, ensure_ascii=False, separators=(",", ":")),
                        now,
                    ),
                )
                connection.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                    (task_status, now, task_id),
                )
                append_operation(
                    connection,
                    task_id,
                    "workbook_uploaded",
                    reason=reason,
                    details={
                        "fileVersionId": file_id,
                        "originalName": file_name,
                        "contentSha256": digest,
                        "sizeBytes": len(content),
                        "inspectionStatus": inspection["status"],
                        "templateVersionId": template["id"],
                        "templateVersionLabel": template["version_label"],
                        "dataImportStatus": data_import["status"] if data_import else None,
                        "totalRecordCount": data_import["totalRecordCount"] if data_import else 0,
                        "blockingIssueCount": data_import["blockingIssueCount"] if data_import else 0,
                        "warningIssueCount": data_import["warningIssueCount"] if data_import else 0,
                        "amountCheckStatus": amount_checks["status"] if amount_checks else None,
                        "amountPassedCount": amount_checks["passedCount"] if amount_checks else 0,
                        "ordinaryReconciliationStatus": ordinary_reconciliation["status"] if ordinary_reconciliation else None,
                        "ordinaryMatchedCount": ordinary_reconciliation["matchedCount"] if ordinary_reconciliation else 0,
                        "ordinaryAttentionCount": ordinary_reconciliation["attentionCount"] if ordinary_reconciliation else 0,
                        "refundReconciliationStatus": refund_reconciliation["status"] if refund_reconciliation else None,
                        "refundMatchedCount": refund_reconciliation["matchedCount"] if refund_reconciliation else 0,
                        "refundAttentionCount": refund_reconciliation["attentionCount"] if refund_reconciliation else 0,
                        "supplementaryReconciliationStatus": supplementary_reconciliation["status"] if supplementary_reconciliation else None,
                        "supplementaryAttentionCount": supplementary_reconciliation["attentionCount"] if supplementary_reconciliation else 0,
                    },
                )
                if data_import is not None and data_import["status"] != "failed":
                    self._refresh_later_supplementary_reconciliations(
                        connection, task_id, now
                    )
                file_row = _select_file_by_id(connection, file_id)
                task_row = _select_task(connection, task_id)
        except sqlite3.IntegrityError:
            _remove_if_present(final_path)
            with connect(self.database_path) as connection:
                duplicate = _select_file_by_digest(connection, task_id, digest)
            if duplicate is not None:
                raise DuplicateFileError(
                    _file_to_api(row_to_dict(duplicate), self.database_path)
                )
            raise
        except Exception:
            _remove_if_present(final_path)
            raise

        return {
            "task": _task_to_api(row_to_dict(task_row)),
            "file": _file_to_api(row_to_dict(file_row), self.database_path),
        }

    def correct_task_period(self, task_id, payload):
        task_id = clean_text(task_id, "任务编号", 80)
        if not isinstance(payload, dict):
            raise ValidationError("修正内容格式不正确")
        target_period = validate_period(payload.get("targetPeriod"))

        with connect(self.database_path) as connection:
            task = _select_task(connection, task_id)
            if task is None:
                raise NotFoundError("没有找到这个对账任务")
            if task["status"] == "completed":
                raise ValidationError("本期已完成，请先填写原因重新打开")
            if task["is_sample"]:
                raise ValidationError("样例任务不能修正，请新建正式任务")
            if task["period"] == target_period:
                raise ValidationError("任务月份已经是{}".format(target_period))

            source_file = connection.execute(
                """
                SELECT f.id, f.original_name, f.stored_name, di.raw_value
                FROM data_issues di
                JOIN data_imports d ON d.id = di.import_id
                JOIN file_versions f ON f.id = d.file_version_id
                WHERE di.task_id = ?
                  AND di.severity = 'blocking'
                  AND di.code = 'task_period_mismatch'
                  AND di.raw_value = ?
                ORDER BY f.created_at DESC, f.id DESC, di.id ASC
                LIMIT 1
                """,
                (task_id, target_period),
            ).fetchone()
            if source_file is None:
                raise ValidationError("只能修正为系统从当前文件识别出的月份")

        source_path = self.upload_dir / source_file["stored_name"]
        if not source_path.is_file():
            raise ValidationError("原始Excel文件缺失，无法重新检查")
        content = source_path.read_bytes()

        corrected_task = self.create_task(
            {
                "entityName": task["entity_name"],
                "storeName": task["store_name"],
                "period": target_period,
            }
        )
        upload_result = self.upload_workbook(
            corrected_task["id"], source_file["original_name"], content
        )
        now = utc_now()
        with connect(self.database_path) as connection:
            append_operation(
                connection,
                task_id,
                "task_period_correction_created",
                reason="根据已导入Excel识别月份生成修正任务",
                details={
                    "oldPeriod": task["period"],
                    "newPeriod": target_period,
                    "sourceFileVersionId": source_file["id"],
                    "correctedTaskId": corrected_task["id"],
                    "preservedOriginalTask": True,
                },
            )
            append_operation(
                connection,
                corrected_task["id"],
                "task_created_from_period_correction",
                reason="保留原任务和原始导入结果后重新检查",
                details={
                    "sourceTaskId": task_id,
                    "sourceFileVersionId": source_file["id"],
                    "oldPeriod": task["period"],
                    "newPeriod": target_period,
                    "createdAt": now,
                },
            )
        result = self.get_task(corrected_task["id"])
        result["correction"] = {
            "sourceTaskId": task_id,
            "sourceFileVersionId": source_file["id"],
            "createdTask": True,
            "preservedOriginalTask": True,
        }
        return result

    def backfill_pending_imports(self):
        """Process structurally valid files saved by an earlier app version once."""
        with connect(self.database_path) as connection:
            pending = connection.execute(
                """
                SELECT f.id, f.task_id, f.stored_name, f.template_version_id, t.period
                FROM file_versions f
                JOIN tasks t ON t.id = f.task_id
                JOIN workbook_inspections i ON i.file_version_id = f.id
                LEFT JOIN data_imports d ON d.file_version_id = f.id
                WHERE i.status = 'passed' AND d.id IS NULL
                ORDER BY f.created_at ASC, f.id ASC
                """
            ).fetchall()

        processed = 0
        for row in pending:
            file_path = self.upload_dir / row["stored_name"]
            if not file_path.is_file():
                continue
            result = analyze_workbook_data(
                file_path,
                row["period"],
                self._definitions_for_template_version(row["template_version_id"]),
            )
            now = utc_now()
            with connect(self.database_path) as connection:
                exists = connection.execute(
                    "SELECT 1 FROM data_imports WHERE file_version_id = ?",
                    (row["id"],),
                ).fetchone()
                if exists is not None:
                    continue
                mapped_records, mapping_summary = _apply_platform_value_mappings(
                    connection, row["task_id"], row["id"], result["records"], now
                )
                result = {
                    **result,
                    "records": mapped_records,
                    "mappingSummary": mapping_summary,
                }
                self._insert_data_import(connection, row["task_id"], row["id"], result, now)
                task_status = "needs_attention" if result["status"] == "failed" else "ready"
                connection.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                    (task_status, now, row["task_id"]),
                )
                append_operation(
                    connection,
                    row["task_id"],
                    "existing_workbook_data_imported",
                    details={
                        "fileVersionId": row["id"],
                        "status": result["status"],
                        "totalRecordCount": result["totalRecordCount"],
                    },
                )
            processed += 1
        return processed

    def _insert_data_import(self, connection, task_id, file_id, result, now):
        import_id = "import-{}".format(uuid.uuid4().hex)
        summary = {
            key: value
            for key, value in result.items()
            if key not in ("records", "issues")
        }
        connection.execute(
            """
            INSERT INTO data_imports (
                id, file_version_id, task_id, status, total_record_count,
                blocking_issue_count, warning_issue_count, summary_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                import_id,
                file_id,
                task_id,
                result["status"],
                result["totalRecordCount"],
                result["blockingIssueCount"],
                result["warningIssueCount"],
                json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                now,
            ),
        )
        connection.executemany(
            """
            INSERT INTO source_records (
                import_id, file_version_id, task_id, sheet_name, row_number,
                record_type, primary_identifier, secondary_identifier,
                event_time, amount_cents, raw_values_json, mapped_values_json,
                mapping_snapshot_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    import_id,
                    file_id,
                    task_id,
                    item["sheetName"],
                    item["rowNumber"],
                    item["recordType"],
                    item["primaryIdentifier"],
                    item["secondaryIdentifier"],
                    item["eventTime"],
                    item["amountCents"],
                    item.get("sourceRawValuesJson", item["rawValuesJson"]),
                    item["rawValuesJson"],
                    item.get("mappingSnapshotJson"),
                    now,
                )
                for item in result["records"]
            ],
        )
        connection.executemany(
            """
            INSERT INTO data_issues (
                import_id, file_version_id, task_id, severity, code,
                sheet_name, row_number, field_name, raw_value,
                message, suggestion, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    import_id,
                    file_id,
                    task_id,
                    item["severity"],
                    item["code"],
                    item["sheetName"],
                    item["rowNumber"],
                    item["fieldName"],
                    item["rawValue"],
                    item["message"],
                    item["suggestion"],
                    now,
                )
                for item in result["issues"]
            ],
        )
        return import_id

    def backfill_pending_amount_checks(self):
        with connect(self.database_path) as connection:
            pending = connection.execute(
                """
                SELECT d.id AS import_id, d.file_version_id, d.task_id,
                       f.stored_name, f.template_version_id,
                       t.rule_version_id, r.tolerance_cents, t.period
                FROM data_imports d
                JOIN file_versions f ON f.id = d.file_version_id
                JOIN tasks t ON t.id = d.task_id
                JOIN rule_versions r ON r.id = t.rule_version_id
                LEFT JOIN amount_check_runs a ON a.import_id = d.id
                WHERE d.status != 'failed' AND a.id IS NULL
                ORDER BY d.created_at ASC, d.id ASC
                """
            ).fetchall()

        processed = 0
        for row in pending:
            file_path = self.upload_dir / row["stored_name"]
            refreshed = None
            if file_path.is_file():
                refreshed = analyze_workbook_data(
                    file_path,
                    row["period"],
                    self._definitions_for_template_version(row["template_version_id"]),
                )
            with connect(self.database_path) as connection:
                if refreshed is not None:
                    records = [
                        item
                        for item in refreshed["records"]
                        if item["recordType"] in ("order", "settlement")
                    ]
                    connection.executemany(
                        """
                        UPDATE source_records
                        SET raw_values_json = ?
                        WHERE import_id = ? AND sheet_name = ? AND row_number = ?
                        """,
                        [
                            (
                                item["rawValuesJson"],
                                row["import_id"],
                                item["sheetName"],
                                item["rowNumber"],
                            )
                            for item in records
                        ],
                    )
                else:
                    source_rows = connection.execute(
                        """
                        SELECT sheet_name, row_number, record_type, primary_identifier,
                               raw_values_json
                        FROM source_records
                        WHERE import_id = ? AND record_type IN ('order', 'settlement')
                        ORDER BY sheet_name, row_number
                        """,
                        (row["import_id"],),
                    ).fetchall()
                    records = [
                        {
                            "sheetName": item["sheet_name"],
                            "rowNumber": item["row_number"],
                            "recordType": item["record_type"],
                            "primaryIdentifier": item["primary_identifier"],
                            "rawValuesJson": item["raw_values_json"],
                        }
                        for item in source_rows
                    ]
                result = calculate_amount_checks(records, row["tolerance_cents"])
                self._insert_amount_checks(
                    connection,
                    row["task_id"],
                    row["file_version_id"],
                    row["import_id"],
                    row["rule_version_id"],
                    result,
                    utc_now(),
                )
                append_operation(
                    connection,
                    row["task_id"],
                    "amount_checks_calculated",
                    details={
                        "fileVersionId": row["file_version_id"],
                        "status": result["status"],
                        "totalCheckCount": result["totalCheckCount"],
                        "passedCount": result["passedCount"],
                    },
                )
            processed += 1
        return processed

    def backfill_pending_reconciliations(self):
        """Calculate R04 once for existing non-blocked imports."""
        with connect(self.database_path) as connection:
            pending = connection.execute(
                """
                SELECT d.id AS import_id, d.file_version_id, d.task_id,
                       t.rule_version_id, r.tolerance_cents
                FROM data_imports d
                JOIN tasks t ON t.id = d.task_id
                JOIN rule_versions r ON r.id = t.rule_version_id
                LEFT JOIN reconciliation_runs rr ON rr.import_id = d.id
                WHERE d.status != 'failed' AND rr.id IS NULL
                ORDER BY d.created_at ASC, d.id ASC
                """
            ).fetchall()

        processed = 0
        for pending_row in pending:
            with connect(self.database_path) as connection:
                source_rows = connection.execute(
                    """
                    SELECT id, sheet_name, row_number, record_type,
                           primary_identifier, secondary_identifier,
                           event_time, amount_cents,
                           COALESCE(mapped_values_json, raw_values_json) AS raw_values_json
                    FROM source_records
                    WHERE import_id = ? AND record_type IN ('settlement', 'fund', 'after_sale')
                    ORDER BY sheet_name, row_number
                    """,
                    (pending_row["import_id"],),
                ).fetchall()
                records = [
                    {
                        "sourceRecordId": item["id"],
                        "sheetName": item["sheet_name"],
                        "rowNumber": item["row_number"],
                        "recordType": item["record_type"],
                        "primaryIdentifier": item["primary_identifier"],
                        "secondaryIdentifier": item["secondary_identifier"],
                        "eventTime": item["event_time"],
                        "amountCents": item["amount_cents"],
                        "rawValuesJson": item["raw_values_json"],
                    }
                    for item in source_rows
                ]
                result = calculate_ordinary_settlement_reconciliation(
                    records, pending_row["tolerance_cents"]
                )
                self._insert_reconciliation(
                    connection,
                    pending_row["task_id"],
                    pending_row["file_version_id"],
                    pending_row["import_id"],
                    pending_row["rule_version_id"],
                    result,
                    utc_now(),
                )
                if result["status"] == "needs_attention":
                    connection.execute(
                        "UPDATE tasks SET status = 'needs_attention', updated_at = ? WHERE id = ?",
                        (utc_now(), pending_row["task_id"]),
                    )
                append_operation(
                    connection,
                    pending_row["task_id"],
                    "ordinary_settlement_reconciled",
                    details={
                        "fileVersionId": pending_row["file_version_id"],
                        "status": result["status"],
                        "totalResultCount": result["totalResultCount"],
                        "matchedCount": result["matchedCount"],
                        "attentionCount": result["attentionCount"],
                    },
                )
            processed += 1
        return processed

    def backfill_pending_refund_reconciliations(self):
        """Calculate R05 once for existing non-blocked imports."""
        with connect(self.database_path) as connection:
            pending = connection.execute(
                """
                SELECT d.id AS import_id, d.file_version_id, d.task_id,
                       t.rule_version_id, r.tolerance_cents,
                       r.refund_auto_group_seconds, r.refund_candidate_seconds
                FROM data_imports d
                JOIN tasks t ON t.id = d.task_id
                JOIN rule_versions r ON r.id = t.rule_version_id
                LEFT JOIN refund_reconciliation_runs rr ON rr.import_id = d.id
                WHERE d.status != 'failed' AND rr.id IS NULL
                ORDER BY d.created_at ASC, d.id ASC
                """
            ).fetchall()

        processed = 0
        for pending_row in pending:
            with connect(self.database_path) as connection:
                source_rows = connection.execute(
                    """
                    SELECT id, sheet_name, row_number, record_type,
                           primary_identifier, secondary_identifier,
                           event_time, amount_cents,
                           COALESCE(mapped_values_json, raw_values_json) AS raw_values_json
                    FROM source_records
                    WHERE import_id = ? AND record_type IN ('settlement', 'fund', 'after_sale')
                    ORDER BY sheet_name, row_number
                    """,
                    (pending_row["import_id"],),
                ).fetchall()
                records = [
                    {
                        "sourceRecordId": item["id"],
                        "sheetName": item["sheet_name"],
                        "rowNumber": item["row_number"],
                        "recordType": item["record_type"],
                        "primaryIdentifier": item["primary_identifier"],
                        "secondaryIdentifier": item["secondary_identifier"],
                        "eventTime": item["event_time"],
                        "amountCents": item["amount_cents"],
                        "rawValuesJson": item["raw_values_json"],
                    }
                    for item in source_rows
                ]
                result = calculate_refund_settlement_reconciliation(
                    records,
                    pending_row["tolerance_cents"],
                    pending_row["refund_auto_group_seconds"],
                    pending_row["refund_candidate_seconds"],
                )
                self._insert_refund_reconciliation(
                    connection,
                    pending_row["task_id"],
                    pending_row["file_version_id"],
                    pending_row["import_id"],
                    pending_row["rule_version_id"],
                    result,
                    utc_now(),
                )
                if result["status"] == "needs_attention":
                    connection.execute(
                        "UPDATE tasks SET status = 'needs_attention', updated_at = ? WHERE id = ?",
                        (utc_now(), pending_row["task_id"]),
                    )
                append_operation(
                    connection,
                    pending_row["task_id"],
                    "refund_settlement_reconciled",
                    details={
                        "fileVersionId": pending_row["file_version_id"],
                        "status": result["status"],
                        "totalResultCount": result["totalResultCount"],
                        "matchedCount": result["matchedCount"],
                        "attentionCount": result["attentionCount"],
                    },
                )
            processed += 1
        return processed

    def backfill_pending_refund_component_checks(self):
        """Add the non-blocking refund component trial to existing R05 rows."""
        with connect(self.database_path) as connection:
            pending = connection.execute(
                """
                SELECT rr.id AS run_id, rr.import_id, rr.file_version_id,
                       rr.task_id, rr.summary_json, rr.tolerance_cents,
                       rr.auto_group_seconds, rr.candidate_seconds
                FROM refund_reconciliation_runs rr
                WHERE EXISTS (
                    SELECT 1 FROM refund_reconciliation_results r
                    WHERE r.run_id = rr.id AND r.component_json IS NULL
                )
                ORDER BY rr.created_at ASC, rr.id ASC
                """
            ).fetchall()

        processed = 0
        for pending_row in pending:
            with connect(self.database_path) as connection:
                records = _load_import_records(connection, pending_row["import_id"])
                result = calculate_refund_settlement_reconciliation(
                    records,
                    pending_row["tolerance_cents"],
                    pending_row["auto_group_seconds"],
                    pending_row["candidate_seconds"],
                )
                calculated_by_row = {
                    item["settlementRowNumber"]: item for item in result["results"]
                }
                stored = connection.execute(
                    """
                    SELECT id, settlement_row_number
                    FROM refund_reconciliation_results
                    WHERE run_id = ?
                    """,
                    (pending_row["run_id"],),
                ).fetchall()
                for row in stored:
                    calculated = calculated_by_row.get(row["settlement_row_number"])
                    if calculated is None:
                        continue
                    connection.execute(
                        """
                        UPDATE refund_reconciliation_results
                        SET component_status = ?, component_json = ?
                        WHERE id = ?
                        """,
                        (
                            calculated.get("componentStatus"),
                            json.dumps(
                                calculated.get("componentCheck") or {},
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                            row["id"],
                        ),
                    )
                summary = json.loads(pending_row["summary_json"])
                summary.update(
                    {key: value for key, value in result.items() if key.startswith("component")}
                )
                connection.execute(
                    "UPDATE refund_reconciliation_runs SET summary_json = ? WHERE id = ?",
                    (
                        json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                        pending_row["run_id"],
                    ),
                )
                append_operation(
                    connection,
                    pending_row["task_id"],
                    "refund_component_trial_backfilled",
                    details={
                        "fileVersionId": pending_row["file_version_id"],
                        "componentStatusCounts": result["componentStatusCounts"],
                        "blocking": False,
                    },
                )
            processed += 1
        return processed

    def backfill_pending_supplementary_reconciliations(self):
        """Calculate R06-R10 once for existing non-blocked imports."""
        with connect(self.database_path) as connection:
            pending = connection.execute(
                """
                SELECT d.id AS import_id, d.file_version_id, d.task_id,
                       t.rule_version_id, t.period, r.settlement_wait_days,
                       r.tolerance_cents
                FROM data_imports d
                JOIN tasks t ON t.id = d.task_id
                JOIN rule_versions r ON r.id = t.rule_version_id
                LEFT JOIN supplementary_reconciliation_runs srr
                       ON srr.import_id = d.id AND srr.is_current = 1
                WHERE d.status != 'failed' AND srr.id IS NULL
                ORDER BY d.created_at ASC, d.id ASC
                """
            ).fetchall()

        processed = 0
        for pending_row in pending:
            with connect(self.database_path) as connection:
                records = _load_import_records(connection, pending_row["import_id"])
                historical_orders = _load_historical_order_records(
                    connection, pending_row["task_id"], pending_row["import_id"]
                )
                result = calculate_supplementary_reconciliation(
                    records,
                    historical_orders,
                    pending_row["settlement_wait_days"],
                    task_period=pending_row["period"],
                    tolerance_cents=pending_row["tolerance_cents"],
                )
                now = utc_now()
                self._insert_supplementary_reconciliation(
                    connection,
                    pending_row["task_id"],
                    pending_row["file_version_id"],
                    pending_row["import_id"],
                    pending_row["rule_version_id"],
                    result,
                    historical_orders,
                    now,
                )
                if result["status"] == "needs_attention":
                    connection.execute(
                        "UPDATE tasks SET status = 'needs_attention', updated_at = ? WHERE id = ?",
                        (now, pending_row["task_id"]),
                    )
                append_operation(
                    connection,
                    pending_row["task_id"],
                    "supplementary_reconciliation_calculated",
                    details={
                        "fileVersionId": pending_row["file_version_id"],
                        "status": result["status"],
                        "missingHistoricalOrderCount": result["crossMonth"]["missingHistoricalOrderCount"],
                        "multipleAfterSaleOrderCount": result["afterSales"]["multipleAfterSaleOrderCount"],
                        "matchedCostCount": result["costs"]["matchedCount"],
                        "otherFundCount": result["otherFunds"]["totalResultCount"],
                    },
                )
            processed += 1
        return processed

    def backfill_current_control_reconciliations(self):
        """Recalculate open V1.1 periods while preserving stable R04/R05 result ids."""
        with connect(self.database_path) as connection:
            candidates = connection.execute(
                """
                SELECT d.id AS import_id, d.file_version_id, d.task_id, t.period,
                       f.stored_name,
                       t.rule_version_id, r.tolerance_cents,
                       r.refund_auto_group_seconds, r.refund_candidate_seconds,
                       r.settlement_wait_days, rr.id AS ordinary_run_id,
                       rr.summary_json AS ordinary_summary_json,
                       rrr.id AS refund_run_id,
                       rrr.summary_json AS refund_summary_json,
                       srr.summary_json AS supplementary_summary_json,
                       f.template_version_id
                FROM tasks t
                JOIN rule_versions r ON r.id = t.rule_version_id
                JOIN file_versions f ON f.task_id = t.id
                JOIN data_imports d ON d.file_version_id = f.id
                JOIN reconciliation_runs rr ON rr.import_id = d.id
                JOIN refund_reconciliation_runs rrr ON rrr.import_id = d.id
                LEFT JOIN supplementary_reconciliation_runs srr
                       ON srr.import_id = d.id AND srr.is_current = 1
                WHERE t.status != 'completed' AND t.rule_version_id = 'rule-v1-1'
                  AND d.status != 'failed'
                  AND f.id = (
                      SELECT f2.id FROM file_versions f2
                      WHERE f2.task_id = t.id
                      ORDER BY f2.created_at DESC, f2.id DESC LIMIT 1
                  )
                ORDER BY t.period, t.id
                """
            ).fetchall()

        processed = 0
        for row in candidates:
            summaries = (
                row["ordinary_summary_json"], row["refund_summary_json"],
                row["supplementary_summary_json"],
            )
            if (
                all(_control_rule_version(value) >= 2 for value in summaries)
                and _source_field_version(row["supplementary_summary_json"]) >= 2
            ):
                continue
            with connect(self.database_path) as connection:
                self._refresh_import_source_values(
                    connection,
                    row["import_id"],
                    row["stored_name"],
                    row["period"],
                    row["template_version_id"],
                )
                records = _load_import_records(connection, row["import_id"])
                historical_orders = _load_historical_order_records(
                    connection, row["task_id"], row["import_id"]
                )
                ordinary = calculate_ordinary_settlement_reconciliation(
                    records, row["tolerance_cents"]
                )
                refund = calculate_refund_settlement_reconciliation(
                    records,
                    row["tolerance_cents"],
                    row["refund_auto_group_seconds"],
                    row["refund_candidate_seconds"],
                )
                supplementary = calculate_supplementary_reconciliation(
                    records,
                    historical_orders,
                    row["settlement_wait_days"],
                    task_period=row["period"],
                    tolerance_cents=row["tolerance_cents"],
                )
                now = utc_now()
                self._update_ordinary_reconciliation(
                    connection, row["ordinary_run_id"], row["rule_version_id"], ordinary
                )
                self._update_refund_reconciliation(
                    connection, row["refund_run_id"], row["rule_version_id"], refund
                )
                self._insert_supplementary_reconciliation(
                    connection,
                    row["task_id"],
                    row["file_version_id"],
                    row["import_id"],
                    row["rule_version_id"],
                    supplementary,
                    historical_orders,
                    now,
                )
                connection.execute(
                    """
                    UPDATE manual_resolution_events SET is_current = 0
                    WHERE task_id = ? AND file_version_id = ? AND is_current = 1
                    """,
                    (row["task_id"], row["file_version_id"]),
                )
                task_status = _task_status_for_file(connection, row["file_version_id"])
                connection.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                    (task_status, now, row["task_id"]),
                )
                append_operation(
                    connection,
                    row["task_id"],
                    "control_rule_v1_1_recalculated",
                    details={
                        "fileVersionId": row["file_version_id"],
                        "ordinaryAttentionCount": ordinary["attentionCount"],
                        "refundAttentionCount": refund["attentionCount"],
                        "supplementaryAttentionCount": supplementary["attentionCount"],
                    },
                )
            processed += 1
        return processed

    def _refresh_import_source_values(
        self, connection, import_id, stored_name, task_period, template_version_id=None
    ):
        """Re-read the retained workbook so newly required source fields remain auditable."""
        workbook_path = self.upload_dir / stored_name
        if not workbook_path.is_file():
            return False
        template = _load_bill_template(
            connection, template_id=template_version_id or DEFAULT_TEMPLATE_ID
        )
        if template is None:
            raise RuntimeError("导入文件对应的账单模板已缺失")
        imported = analyze_workbook_data(
            workbook_path, task_period, _bill_template_definitions(template)
        )
        fresh_by_row = {
            (item["sheetName"], item["rowNumber"]): item
            for item in imported.get("records") or []
        }
        rows = connection.execute(
            "SELECT id, sheet_name, row_number FROM source_records WHERE import_id = ?",
            (import_id,),
        ).fetchall()
        for source in rows:
            fresh = fresh_by_row.get((source["sheet_name"], source["row_number"]))
            if fresh is None:
                continue
            connection.execute(
                """
                UPDATE source_records
                SET primary_identifier = ?, secondary_identifier = ?, event_time = ?,
                    amount_cents = ?, raw_values_json = ?
                WHERE id = ?
                """,
                (
                    fresh.get("primaryIdentifier"), fresh.get("secondaryIdentifier"),
                    fresh.get("eventTime"), fresh.get("amountCents"),
                    fresh.get("rawValuesJson"), source["id"],
                ),
            )
        return True

    def _update_ordinary_reconciliation(self, connection, run_id, rule_version_id, result):
        summary = {key: value for key, value in result.items() if key != "results"}
        connection.execute(
            """
            UPDATE reconciliation_runs
            SET rule_version_id = ?, status = ?, total_result_count = ?, matched_count = ?,
                attention_count = ?, settlement_amount_total_cents = ?,
                matched_fund_amount_total_cents = ?, difference_total_cents = ?,
                tolerance_cents = ?, summary_json = ?
            WHERE id = ?
            """,
            (
                rule_version_id, result["status"], result["totalResultCount"],
                result["matchedCount"], result["attentionCount"],
                result["settlementAmountTotalCents"], result["matchedFundAmountTotalCents"],
                result["differenceTotalCents"], result["toleranceCents"],
                json.dumps(summary, ensure_ascii=False, separators=(",", ":")), run_id,
            ),
        )
        for item in result["results"]:
            candidates = item.get("candidateRecords") or []
            fund_record_id = next(
                (candidate.get("sourceRecordId") for candidate in candidates
                 if candidate.get("rowNumber") == item.get("fundRowNumber")),
                None,
            )
            connection.execute(
                """
                UPDATE reconciliation_results
                SET status = ?, fund_record_id = ?, fund_row_number = ?,
                    fund_primary_identifier = ?, fund_amount_cents = ?, difference_cents = ?,
                    candidate_count = ?, matched_candidate_count = ?,
                    candidate_records_json = ?, explanation = ?, suggestion = ?
                WHERE run_id = ? AND settlement_row_number = ?
                """,
                (
                    item["status"], fund_record_id, item.get("fundRowNumber"),
                    item.get("fundTransactionId"), item.get("fundAmountCents"),
                    item.get("differenceCents"), item["candidateCount"],
                    item["matchedCandidateCount"],
                    json.dumps(candidates, ensure_ascii=False, separators=(",", ":")),
                    item["explanation"], item["suggestion"], run_id,
                    item["settlementRowNumber"],
                ),
            )

    def _update_refund_reconciliation(self, connection, run_id, rule_version_id, result):
        summary = {key: value for key, value in result.items() if key != "results"}
        connection.execute(
            """
            UPDATE refund_reconciliation_runs
            SET rule_version_id = ?, status = ?, total_result_count = ?, matched_count = ?,
                attention_count = ?, settlement_amount_total_cents = ?,
                matched_fund_amount_total_cents = ?, difference_total_cents = ?,
                tolerance_cents = ?, auto_group_seconds = ?, candidate_seconds = ?,
                summary_json = ?
            WHERE id = ?
            """,
            (
                rule_version_id, result["status"], result["totalResultCount"],
                result["matchedCount"], result["attentionCount"],
                result["settlementAmountTotalCents"], result["matchedFundAmountTotalCents"],
                result["differenceTotalCents"], result["toleranceCents"],
                result["autoGroupSeconds"], result["candidateSeconds"],
                json.dumps(summary, ensure_ascii=False, separators=(",", ":")), run_id,
            ),
        )
        for item in result["results"]:
            connection.execute(
                """
                UPDATE refund_reconciliation_results
                SET status = ?, fund_net_amount_cents = ?, difference_cents = ?,
                    after_sale_id = ?, max_time_difference_seconds = ?,
                    candidate_count = ?, candidate_group_count = ?,
                    matched_candidate_count = ?, selected_records_json = ?,
                    candidate_groups_json = ?, component_status = ?, component_json = ?,
                    explanation = ?, suggestion = ?
                WHERE run_id = ? AND settlement_row_number = ?
                """,
                (
                    item["status"], item.get("fundNetAmountCents"),
                    item.get("differenceCents"), item.get("afterSaleId"),
                    item.get("maxTimeDifferenceSeconds"), item["candidateCount"],
                    item["candidateGroupCount"], item["matchedCandidateCount"],
                    json.dumps(item.get("selectedRecords") or [], ensure_ascii=False, separators=(",", ":")),
                    json.dumps(item.get("candidateGroups") or [], ensure_ascii=False, separators=(",", ":")),
                    item.get("componentStatus"),
                    json.dumps(item.get("componentCheck") or {}, ensure_ascii=False, separators=(",", ":")),
                    item["explanation"], item["suggestion"], run_id,
                    item["settlementRowNumber"],
                ),
            )

    def _refresh_later_supplementary_reconciliations(
        self, connection, source_task_id, now
    ):
        """Refresh later open periods after an earlier-period file becomes available."""
        source_task = connection.execute(
            "SELECT entity_name, store_name, period FROM tasks WHERE id = ?",
            (source_task_id,),
        ).fetchone()
        if source_task is None:
            return 0
        later_imports = connection.execute(
            """
            SELECT d.id AS import_id, d.file_version_id, d.task_id,
                   t.rule_version_id, r.settlement_wait_days, r.tolerance_cents,
                   t.period
            FROM tasks t
            JOIN rule_versions r ON r.id = t.rule_version_id
            JOIN file_versions f ON f.task_id = t.id
            JOIN data_imports d ON d.file_version_id = f.id
            WHERE t.entity_name = ? AND t.store_name = ?
              AND t.period > ? AND t.status != 'completed'
              AND d.status != 'failed'
              AND f.id = (
                  SELECT f2.id
                  FROM file_versions f2
                  WHERE f2.task_id = t.id
                  ORDER BY f2.created_at DESC, f2.id DESC
                  LIMIT 1
              )
            ORDER BY t.period ASC, t.id ASC
            """,
            (
                source_task["entity_name"],
                source_task["store_name"],
                source_task["period"],
            ),
        ).fetchall()
        refreshed = 0
        for later in later_imports:
            records = _load_import_records(connection, later["import_id"])
            historical_orders = _load_historical_order_records(
                connection, later["task_id"], later["import_id"]
            )
            result = calculate_supplementary_reconciliation(
                records,
                historical_orders,
                later["settlement_wait_days"],
                task_period=later["period"],
                tolerance_cents=later["tolerance_cents"],
            )
            self._insert_supplementary_reconciliation(
                connection,
                later["task_id"],
                later["file_version_id"],
                later["import_id"],
                later["rule_version_id"],
                result,
                historical_orders,
                now,
            )
            task_status = _task_status_for_file(connection, later["file_version_id"])
            connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (task_status, now, later["task_id"]),
            )
            append_operation(
                connection,
                later["task_id"],
                "supplementary_reconciliation_refreshed",
                details={
                    "fileVersionId": later["file_version_id"],
                    "triggerTaskId": source_task_id,
                    "triggerPeriod": source_task["period"],
                    "status": result["status"],
                    "missingHistoricalOrderCount": result["crossMonth"]["missingHistoricalOrderCount"],
                    "historicalOrderFoundCount": result["crossMonth"]["historicalOrderFoundCount"],
                },
            )
            refreshed += 1
        return refreshed

    def _insert_reconciliation(
        self, connection, task_id, file_id, import_id, rule_version_id, result, now
    ):
        run_id = "reconciliation-run-{}".format(uuid.uuid4().hex)
        summary = {key: value for key, value in result.items() if key != "results"}
        connection.execute(
            """
            INSERT INTO reconciliation_runs (
                id, import_id, file_version_id, task_id, rule_version_id,
                result_type, status, total_result_count, matched_count,
                attention_count, settlement_amount_total_cents,
                matched_fund_amount_total_cents, difference_total_cents,
                tolerance_cents, summary_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                import_id,
                file_id,
                task_id,
                rule_version_id,
                result["resultType"],
                result["status"],
                result["totalResultCount"],
                result["matchedCount"],
                result["attentionCount"],
                result["settlementAmountTotalCents"],
                result["matchedFundAmountTotalCents"],
                result["differenceTotalCents"],
                result["toleranceCents"],
                json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                now,
            ),
        )

        source_rows = connection.execute(
            """
            SELECT id, sheet_name, row_number
            FROM source_records
            WHERE import_id = ? AND sheet_name IN ('结算账单', '资金账单')
            """,
            (import_id,),
        ).fetchall()
        source_ids = {
            (item["sheet_name"], item["row_number"]): item["id"] for item in source_rows
        }
        insert_rows = []
        for item in result["results"]:
            settlement_record_id = source_ids.get(("结算账单", item["settlementRowNumber"]))
            if settlement_record_id is None:
                raise RuntimeError("普通结算核对结果缺少结算源记录")
            fund_record_id = None
            if item["fundRowNumber"]:
                fund_record_id = source_ids.get(("资金账单", item["fundRowNumber"]))
            candidates = []
            for candidate in item["candidateRecords"]:
                candidates.append(
                    {
                        **candidate,
                        "sourceRecordId": source_ids.get(("资金账单", candidate["rowNumber"])),
                    }
                )
            insert_rows.append(
                (
                    "reconciliation-result-{}".format(uuid.uuid4().hex),
                    run_id,
                    import_id,
                    file_id,
                    task_id,
                    result["resultType"],
                    item["status"],
                    item["subOrderId"],
                    settlement_record_id,
                    item["settlementRowNumber"],
                    item["settlementAmountCents"],
                    fund_record_id,
                    item["fundRowNumber"],
                    item["fundTransactionId"],
                    item["fundAmountCents"],
                    item["differenceCents"],
                    item["candidateCount"],
                    item["matchedCandidateCount"],
                    json.dumps(candidates, ensure_ascii=False, separators=(",", ":")),
                    item["explanation"],
                    item["suggestion"],
                    now,
                )
            )
        connection.executemany(
            """
            INSERT INTO reconciliation_results (
                id, run_id, import_id, file_version_id, task_id, result_type,
                status, primary_identifier, settlement_record_id,
                settlement_row_number, settlement_amount_cents, fund_record_id,
                fund_row_number, fund_primary_identifier, fund_amount_cents,
                difference_cents, candidate_count, matched_candidate_count,
                candidate_records_json, explanation, suggestion, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            insert_rows,
        )
        return run_id

    def _insert_refund_reconciliation(
        self, connection, task_id, file_id, import_id, rule_version_id, result, now
    ):
        run_id = "refund-reconciliation-run-{}".format(uuid.uuid4().hex)
        summary = {key: value for key, value in result.items() if key != "results"}
        connection.execute(
            """
            INSERT INTO refund_reconciliation_runs (
                id, import_id, file_version_id, task_id, rule_version_id,
                result_type, status, total_result_count, matched_count,
                attention_count, settlement_amount_total_cents,
                matched_fund_amount_total_cents, difference_total_cents,
                tolerance_cents, auto_group_seconds, candidate_seconds,
                summary_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                import_id,
                file_id,
                task_id,
                rule_version_id,
                result["resultType"],
                result["status"],
                result["totalResultCount"],
                result["matchedCount"],
                result["attentionCount"],
                result["settlementAmountTotalCents"],
                result["matchedFundAmountTotalCents"],
                result["differenceTotalCents"],
                result["toleranceCents"],
                result["autoGroupSeconds"],
                result["candidateSeconds"],
                json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                now,
            ),
        )

        source_rows = connection.execute(
            """
            SELECT id, sheet_name, row_number
            FROM source_records
            WHERE import_id = ? AND sheet_name IN ('结算账单', '资金账单')
            """,
            (import_id,),
        ).fetchall()
        source_ids = {
            (item["sheet_name"], item["row_number"]): item["id"] for item in source_rows
        }

        def attach_source_id(record):
            return {
                **record,
                "sourceRecordId": record.get("sourceRecordId")
                or source_ids.get(("资金账单", record.get("rowNumber"))),
            }

        insert_rows = []
        for item in result["results"]:
            settlement_record_id = source_ids.get(("结算账单", item["settlementRowNumber"]))
            if settlement_record_id is None:
                raise RuntimeError("退款结算核对结果缺少结算源记录")
            selected_records = [attach_source_id(record) for record in item["selectedRecords"]]
            candidate_groups = []
            for group in item["candidateGroups"]:
                candidate_groups.append(
                    {
                        **group,
                        "records": [attach_source_id(record) for record in group["records"]],
                    }
                )
            insert_rows.append(
                (
                    "refund-reconciliation-result-{}".format(uuid.uuid4().hex),
                    run_id,
                    import_id,
                    file_id,
                    task_id,
                    item["status"],
                    item["subOrderId"],
                    settlement_record_id,
                    item["settlementRowNumber"],
                    item["settlementAmountCents"],
                    item["fundNetAmountCents"],
                    item["differenceCents"],
                    item["afterSaleId"],
                    item["maxTimeDifferenceSeconds"],
                    item["candidateCount"],
                    item["candidateGroupCount"],
                    item["matchedCandidateCount"],
                    json.dumps(selected_records, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(candidate_groups, ensure_ascii=False, separators=(",", ":")),
                    item.get("componentStatus"),
                    json.dumps(
                        item.get("componentCheck") or {},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    item["explanation"],
                    item["suggestion"],
                    now,
                )
            )
        connection.executemany(
            """
            INSERT INTO refund_reconciliation_results (
                id, run_id, import_id, file_version_id, task_id, status,
                primary_identifier, settlement_record_id, settlement_row_number,
                settlement_amount_cents, fund_net_amount_cents, difference_cents,
                after_sale_id, max_time_difference_seconds, candidate_count,
                candidate_group_count, matched_candidate_count,
                selected_records_json, candidate_groups_json,
                component_status, component_json,
                explanation, suggestion, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            insert_rows,
        )
        return run_id

    def _insert_supplementary_reconciliation(
        self, connection, task_id, file_id, import_id, rule_version_id,
        result, historical_orders, now,
    ):
        connection.execute(
            """
            UPDATE supplementary_reconciliation_runs
            SET is_current = 0, superseded_at = ?
            WHERE import_id = ? AND is_current = 1
            """,
            (now, import_id),
        )
        run_id = "supplementary-run-{}".format(uuid.uuid4().hex)
        summary = {
            key: (
                {section_key: section_value for section_key, section_value in value.items()
                 if section_key != "results"}
                if key in ("crossMonth", "afterSales", "costs", "otherFunds")
                else value
            )
            for key, value in result.items()
        }
        snapshot_import_ids = sorted(
            {item.get("importId") for item in historical_orders if item.get("importId")}
        )
        source_snapshot = {
            "currentImportId": import_id,
            "historicalImportIds": snapshot_import_ids,
        }
        connection.execute(
            """
            INSERT INTO supplementary_reconciliation_runs (
                id, import_id, file_version_id, task_id, rule_version_id,
                result_type, status, settlement_wait_days, attention_count,
                summary_json, source_snapshot_json, is_current, created_at
            ) VALUES (?, ?, ?, ?, ?, 'supplementary', ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                run_id,
                import_id,
                file_id,
                task_id,
                rule_version_id,
                result["status"],
                result["settlementWaitDays"],
                result["attentionCount"],
                json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                json.dumps(source_snapshot, ensure_ascii=False, separators=(",", ":")),
                now,
            ),
        )

        insert_rows = []
        for section_key in ("crossMonth", "afterSales", "costs", "otherFunds"):
            for item in result[section_key]["results"]:
                source_record_id = item.get("sourceRecordId")
                if source_record_id is None:
                    raise RuntimeError("补充核对结果缺少源记录")
                primary_identifier, linked_id, linked_row, amount, calculated, group_key = (
                    _supplementary_storage_fields(item)
                )
                insert_rows.append(
                    (
                        "supplementary-result-{}".format(uuid.uuid4().hex),
                        run_id,
                        import_id,
                        file_id,
                        task_id,
                        item["resultType"],
                        item["status"],
                        primary_identifier,
                        source_record_id,
                        item["sourceRowNumber"],
                        linked_id,
                        linked_row,
                        amount,
                        calculated,
                        group_key,
                        json.dumps(
                            _supplementary_metadata(item),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        item["explanation"],
                        item["suggestion"],
                        now,
                    )
                )
        connection.executemany(
            """
            INSERT INTO supplementary_reconciliation_results (
                id, run_id, import_id, file_version_id, task_id,
                result_type, status, primary_identifier, source_record_id,
                source_row_number, linked_source_record_id, linked_row_number,
                amount_cents, calculated_amount_cents, group_key,
                metadata_json, explanation, suggestion, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            insert_rows,
        )
        return run_id

    def _insert_amount_checks(
        self, connection, task_id, file_id, import_id, rule_version_id, result, now
    ):
        run_id = "amount-run-{}".format(uuid.uuid4().hex)
        summary = {
            key: value for key, value in result.items() if key != "results"
        }
        connection.execute(
            """
            INSERT INTO amount_check_runs (
                id, import_id, file_version_id, task_id, rule_version_id, status,
                total_check_count, passed_count, failed_count, not_calculable_count,
                summary_json, created_at, tolerance_cents
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                import_id,
                file_id,
                task_id,
                rule_version_id,
                result["status"],
                result["totalCheckCount"],
                result["passedCount"],
                result["failedCount"],
                result["notCalculableCount"],
                json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                now,
                result["toleranceCents"],
            ),
        )
        connection.executemany(
            """
            INSERT INTO amount_check_results (
                run_id, import_id, file_version_id, task_id, sheet_name,
                row_number, record_type, primary_identifier, check_code,
                check_label, status, source_amount_cents,
                calculated_amount_cents, difference_cents, message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    import_id,
                    file_id,
                    task_id,
                    item["sheetName"],
                    item["rowNumber"],
                    item["recordType"],
                    item["primaryIdentifier"],
                    item["checkCode"],
                    item["checkLabel"],
                    item["status"],
                    item["sourceAmountCents"],
                    item["calculatedAmountCents"],
                    item["differenceCents"],
                    item["message"],
                    now,
                )
                for item in result["results"]
            ],
        )
        return run_id


def _load_import_records(connection, import_id):
    rows = connection.execute(
        """
        SELECT id, import_id, file_version_id, task_id, sheet_name, row_number,
               record_type, primary_identifier, secondary_identifier,
               event_time, amount_cents,
               COALESCE(mapped_values_json, raw_values_json) AS raw_values_json
        FROM source_records
        WHERE import_id = ?
        ORDER BY sheet_name, row_number
        """,
        (import_id,),
    ).fetchall()
    return [
        {
            "sourceRecordId": item["id"],
            "importId": item["import_id"],
            "fileVersionId": item["file_version_id"],
            "taskId": item["task_id"],
            "sheetName": item["sheet_name"],
            "rowNumber": item["row_number"],
            "recordType": item["record_type"],
            "primaryIdentifier": item["primary_identifier"],
            "secondaryIdentifier": item["secondary_identifier"],
            "eventTime": item["event_time"],
            "amountCents": item["amount_cents"],
            "rawValuesJson": item["raw_values_json"],
        }
        for item in rows
    ]


def _load_historical_order_records(connection, task_id, current_import_id):
    task = connection.execute(
        "SELECT entity_name, store_name, period FROM tasks WHERE id = ?",
        (task_id,),
    ).fetchone()
    if task is None:
        return []
    rows = connection.execute(
        """
        SELECT sr.id, sr.import_id, sr.file_version_id, sr.task_id,
               sr.sheet_name, sr.row_number, sr.record_type,
               sr.primary_identifier, sr.secondary_identifier,
               sr.event_time, sr.amount_cents,
               COALESCE(sr.mapped_values_json, sr.raw_values_json) AS raw_values_json,
               t.period AS task_period
        FROM source_records sr
        JOIN data_imports d ON d.id = sr.import_id
        JOIN tasks t ON t.id = sr.task_id
        JOIN file_versions f ON f.id = sr.file_version_id
        WHERE sr.record_type = 'order'
          AND d.status != 'failed'
          AND d.id != ?
          AND t.entity_name = ? AND t.store_name = ?
          AND t.period < ?
          AND d.id = (
              SELECT d2.id
              FROM data_imports d2
              JOIN file_versions f2 ON f2.id = d2.file_version_id
              WHERE d2.task_id = t.id AND d2.status != 'failed'
              ORDER BY f2.created_at DESC, f2.id DESC
              LIMIT 1
          )
        ORDER BY t.period DESC, sr.row_number
        """,
        (
            current_import_id,
            task["entity_name"],
            task["store_name"],
            task["period"],
        ),
    ).fetchall()
    return [
        {
            "sourceRecordId": item["id"],
            "importId": item["import_id"],
            "fileVersionId": item["file_version_id"],
            "taskId": item["task_id"],
            "taskPeriod": item["task_period"],
            "sheetName": item["sheet_name"],
            "rowNumber": item["row_number"],
            "recordType": item["record_type"],
            "primaryIdentifier": item["primary_identifier"],
            "secondaryIdentifier": item["secondary_identifier"],
            "eventTime": item["event_time"],
            "amountCents": item["amount_cents"],
            "rawValuesJson": item["raw_values_json"],
        }
        for item in rows
    ]


def _supplementary_storage_fields(item):
    result_type = item["resultType"]
    if result_type == "cross_month":
        return (
            item.get("subOrderId"), item.get("linkedSourceRecordId"),
            item.get("linkedRowNumber"), item.get("amountCents"),
            item.get("expectedMerchantReceivableCents")
            if item.get("recordKind") != "unsettled_order"
            else item.get("successfulRefundCents"),
            item.get("recordKind") or item.get("orderPeriod"),
        )
    if result_type == "after_sale":
        return (
            item.get("afterSaleId"), None, None, item.get("amountCents"), None,
            item.get("subOrderId"),
        )
    if result_type == "cost":
        return (
            item.get("subOrderId"), item.get("linkedSourceRecordId"),
            item.get("linkedRowNumber"), item.get("orderAmountCents"),
            item.get("totalCostCents"), item.get("sku"),
        )
    return (
        item.get("transactionId"), None, None, item.get("amountCents"), None,
        item.get("category"),
    )


def _supplementary_metadata(item):
    excluded = {
        "resultType", "status", "sourceRecordId", "sourceRowNumber",
        "linkedSourceRecordId", "linkedRowNumber", "explanation", "suggestion",
    }
    return {key: value for key, value in item.items() if key not in excluded}


def _control_rule_version(summary_json):
    try:
        summary = json.loads(summary_json or "{}")
        return int(summary.get("controlRuleVersion") or 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0


def _source_field_version(summary_json):
    try:
        summary = json.loads(summary_json or "{}")
        return int(summary.get("sourceFieldVersion") or 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0


def _supplementary_statuses(result_type):
    statuses = {
        "cross_month": {
            "order_found_current", "order_found_history", "missing_historical_order",
            "missing_order_data", "multiple_history_orders",
            "settlement_receivable_mismatch", "settlement_receivable_not_calculable",
            "settlement_before_refund_review", "possibly_unsettled", "not_calculable",
            "order_status_requires_review", "normal_waiting", "waiting_after_sale",
            "fully_refunded_no_settlement", "closed_no_settlement",
        },
        "after_sale": {
            "refund_success", "after_sale_closed", "exchange_success",
            "waiting_after_sale", "new_after_sale_status", "after_sale_refund_conflict",
            "refund_missing_after_sale",
        },
        "cost": {
            "matched_static_cost", "missing_sku", "missing_cost",
            "multiple_cost_candidates", "not_calculable",
        },
        "other_fund": {"classified", "waiting_classification"},
    }
    return statuses[result_type]


def _supplementary_filter_sql(result_type, status):
    attention = sorted(SUPPLEMENTARY_RESULT_TYPES[result_type]["attention"])
    if status == "all":
        return "", []
    if status == "needs_attention":
        return " AND r.status IN ({})".format(",".join("?" for _ in attention)), attention
    if status == "cleared":
        return " AND r.status NOT IN ({})".format(",".join("?" for _ in attention)), attention
    return " AND r.status = ?", [status]


def _load_bill_template(connection, template_id=None, status=None):
    if template_id is not None:
        row = connection.execute(
            "SELECT * FROM bill_template_versions WHERE id = ?", (template_id,)
        ).fetchone()
    else:
        row = connection.execute(
            """
            SELECT * FROM bill_template_versions
            WHERE status = ?
            ORDER BY activated_at DESC, created_at DESC
            LIMIT 1
            """,
            (status or "current",),
        ).fetchone()
    if row is None:
        return None
    result = row_to_dict(row)
    sheet_rows = connection.execute(
        """
        SELECT * FROM bill_template_sheets
        WHERE template_version_id = ?
        ORDER BY sort_order, id
        """,
        (result["id"],),
    ).fetchall()
    result["sheets"] = []
    for sheet_row in sheet_rows:
        sheet = row_to_dict(sheet_row)
        field_rows = connection.execute(
            """
            SELECT * FROM bill_template_fields
            WHERE sheet_id = ?
            ORDER BY sort_order, id
            """,
            (sheet["id"],),
        ).fetchall()
        sheet["fields"] = [row_to_dict(item) for item in field_rows]
        result["sheets"].append(sheet)
    return result


def _bill_template_to_api(connection, template_row):
    template = _load_bill_template(connection, template_id=template_row["id"])
    return {
        "id": template["id"],
        "platformCode": template["platform_code"],
        "templateCode": template["template_code"],
        "versionLabel": template["version_label"],
        "name": template["name"],
        "status": template["status"],
        "notes": template["notes"],
        "lastTestedAt": template["last_tested_at"],
        "lastTestStatus": template["last_test_status"],
        "lastTestFileName": template["last_test_file_name"],
        "lastTestSummary": json.loads(template["last_test_summary_json"] or "null"),
        "createdAt": template["created_at"],
        "updatedAt": template["updated_at"],
        "activatedAt": template["activated_at"],
        "sheets": [
            {
                "id": sheet["id"],
                "standardSheetCode": sheet["standard_sheet_code"],
                "displayName": sheet["display_name"],
                "sourceSheetName": sheet["source_sheet_name"],
                "sourceSheetAliases": json.loads(
                    sheet["source_sheet_aliases_json"] or "[]"
                ),
                "headerRow": sheet["header_row"],
                "dataStartRow": sheet["data_start_row"],
                "baselineRows": sheet["baseline_rows"],
                "baselineColumns": sheet["baseline_columns"],
                "required": bool(sheet["required"]),
                "fields": [
                    {
                        "id": field["id"],
                        "standardFieldCode": field["standard_field_code"],
                        "displayName": field["display_name"],
                        "sourceHeader": field["source_header"],
                        "sourceAliases": json.loads(
                            field["source_aliases_json"] or "[]"
                        ),
                        "dataType": field["data_type"],
                        "required": bool(field["required"]),
                    }
                    for field in sheet["fields"]
                ],
            }
            for sheet in template["sheets"]
        ],
    }


def _bill_template_definitions(template):
    definitions = []
    for sheet in template["sheets"]:
        field_aliases = {}
        configured_headers = []
        required_headers = []
        for field in sheet["fields"]:
            canonical = field["display_name"]
            configured_headers.append(canonical)
            if field["required"]:
                required_headers.append(canonical)
            aliases = [field["source_header"]]
            aliases.extend(json.loads(field["source_aliases_json"] or "[]"))
            field_aliases[canonical] = aliases
        definitions.append({
            "name": sheet["display_name"],
            "source_name": sheet["source_sheet_name"],
            "sheet_aliases": json.loads(sheet["source_sheet_aliases_json"] or "[]"),
            "header_row": sheet["header_row"],
            "data_start_row": sheet["data_start_row"],
            "baseline_rows": sheet["baseline_rows"],
            "baseline_columns": sheet["baseline_columns"],
            "required_headers": tuple(required_headers),
            "configured_headers": tuple(configured_headers),
            "field_aliases": field_aliases,
        })
    return definitions


def _next_version_label(labels):
    versions = []
    for label in labels:
        match = re.fullmatch(r"V(\d+)\.(\d+)", label or "")
        if match:
            versions.append((int(match.group(1)), int(match.group(2))))
    major, minor = max(versions or [(1, -1)])
    return "V{}.{}".format(major, minor + 1)


def _validate_aliases(value, field_name):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError("{}必须是列表".format(field_name))
    if len(value) > 20:
        raise ValidationError("{}最多20个".format(field_name))
    result = []
    for item in value:
        cleaned = clean_text(item, field_name, 120)
        if cleaned not in result:
            result.append(cleaned)
    return result


def _validate_positive_int(value, field_name, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("{}必须是整数".format(field_name))
    if value < 1 or value > maximum:
        raise ValidationError("{}必须在1到{}之间".format(field_name, maximum))
    return value


def _validate_bounded_int(value, field_name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("{}必须是整数".format(field_name))
    if value < minimum or value > maximum:
        raise ValidationError(
            "{}必须在{}到{}之间".format(field_name, minimum, maximum)
        )
    return value


def _validate_date(value, field_name):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValidationError("{}必须使用YYYY-MM-DD格式".format(field_name))
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValidationError("{}不是有效日期".format(field_name))
    return value


def _find_or_create_master_store(connection, entity_name, store_name, now):
    entity = connection.execute(
        "SELECT * FROM business_entities WHERE name = ?", (entity_name,)
    ).fetchone()
    if entity is None:
        entity_id = "entity-{}".format(uuid.uuid4().hex)
        connection.execute(
            """
            INSERT INTO business_entities (id, name, status, created_at, updated_at)
            VALUES (?, ?, 'active', ?, ?)
            """,
            (entity_id, entity_name, now, now),
        )
    else:
        if entity["status"] != "active":
            raise ValidationError("企业主体已停用，请先在配置中心启用")
        entity_id = entity["id"]
    store = connection.execute(
        """
        SELECT * FROM platform_stores
        WHERE entity_id = ? AND platform_code = 'DOUYIN' AND name = ?
        """,
        (entity_id, store_name),
    ).fetchone()
    if store is None:
        store_id = "store-{}".format(uuid.uuid4().hex)
        connection.execute(
            """
            INSERT INTO platform_stores (
                id, entity_id, platform_code, name, status, created_at, updated_at
            ) VALUES (?, ?, 'DOUYIN', ?, 'active', ?, ?)
            """,
            (store_id, entity_id, store_name, now, now),
        )
    else:
        if store["status"] != "active":
            raise ValidationError("店铺已停用，请先在配置中心启用")
        store_id = store["id"]
    return entity_id, store_id


def _master_data_to_api(rows):
    entities = {}
    for row in rows:
        entity = entities.setdefault(
            row["entity_id"],
            {
                "id": row["entity_id"],
                "name": row["entity_name"],
                "status": row["entity_status"],
                "stores": [],
            },
        )
        if row["store_id"] is not None:
            entity["stores"].append({
                "id": row["store_id"],
                "name": row["store_name"],
                "platformCode": row["platform_code"],
                "status": row["store_status"],
                "taskCount": row["task_count"] or 0,
                "lastUsedAt": row["last_used_at"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
            })
    return list(entities.values())


def _mapping_types_to_api():
    return [
        {
            "code": code,
            "name": definition["name"],
            "sourceField": definition["sourceField"],
            "standards": [
                {
                    "code": item["code"],
                    "name": item["name"],
                    "canonicalValue": item["canonicalValue"],
                }
                for item in definition["standards"]
            ],
        }
        for code, definition in VALUE_MAPPING_TYPES.items()
    ]


def _value_mapping_to_api(row):
    return {
        "id": row["id"],
        "mappingType": row["mapping_type"],
        "mappingTypeName": VALUE_MAPPING_TYPES[row["mapping_type"]]["name"],
        "sourceValue": row["source_value"],
        "standardCode": row["standard_code"],
        "standardName": row["standard_name"],
        "canonicalValue": row["canonical_value"],
        "versionNumber": row["version_number"],
        "versionLabel": row["version_label"],
        "effectiveFrom": row["effective_from"],
        "isCurrent": bool(row["is_current"]),
        "notes": row["notes"],
        "createdAt": row["created_at"],
    }


def _unmapped_value_to_api(row):
    return {
        "id": row["id"],
        "mappingType": row["mapping_type"],
        "mappingTypeName": VALUE_MAPPING_TYPES[row["mapping_type"]]["name"],
        "sourceValue": row["source_value"],
        "occurrenceCount": row["occurrence_count"],
        "firstSeenAt": row["first_seen_at"],
        "lastSeenAt": row["last_seen_at"],
        "latestTaskId": row["latest_task_id"],
        "entityName": row.get("entity_name"),
        "storeName": row.get("store_name"),
        "status": row["status"],
    }


def _apply_platform_value_mappings(connection, task_id, file_id, records, now):
    task = connection.execute(
        "SELECT period FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    default_event_date = "{}-01".format(task["period"]) if task else "2000-01-01"
    mapping_rows = connection.execute(
        """
        SELECT * FROM platform_value_mappings
        ORDER BY mapping_type, source_value, effective_from DESC, version_number DESC
        """
    ).fetchall()
    mappings_by_key = {}
    for row in mapping_rows:
        mappings_by_key.setdefault((row["mapping_type"], row["source_value"]), []).append(row)
    type_by_record = {
        definition["recordType"]: (mapping_type, definition)
        for mapping_type, definition in VALUE_MAPPING_TYPES.items()
    }
    applied_ids = set()
    pending_values = set()
    pending_record_count = 0
    mapped_records = []
    for record in records:
        source_json = record["rawValuesJson"]
        source_values = json.loads(source_json or "{}")
        mapped_values = dict(source_values)
        snapshot = {}
        type_info = type_by_record.get(record.get("recordType"))
        if type_info is not None:
            mapping_type, definition = type_info
            field_name = definition["sourceField"]
            source_value = " ".join(str(source_values.get(field_name) or "").strip().split())
            if source_value:
                event_time = record.get("eventTime") or ""
                event_date = event_time[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_time[:10]) else default_event_date
                candidates = mappings_by_key.get((mapping_type, source_value), [])
                mapping = next(
                    (item for item in candidates if item["effective_from"] <= event_date),
                    None,
                )
                if mapping is not None:
                    mapped_values[field_name] = mapping["canonical_value"]
                    applied_ids.add(mapping["id"])
                    snapshot[field_name] = {
                        "mappingId": mapping["id"],
                        "mappingType": mapping_type,
                        "sourceValue": source_value,
                        "standardCode": mapping["standard_code"],
                        "standardName": mapping["standard_name"],
                        "canonicalValue": mapping["canonical_value"],
                        "versionLabel": mapping["version_label"],
                        "effectiveFrom": mapping["effective_from"],
                    }
                else:
                    pending_values.add((mapping_type, source_value))
                    pending_record_count += 1
                    existing_unmapped = connection.execute(
                        """
                        SELECT id FROM unmapped_platform_values
                        WHERE mapping_type = ? AND source_value = ?
                        """,
                        (mapping_type, source_value),
                    ).fetchone()
                    if existing_unmapped is None:
                        connection.execute(
                            """
                            INSERT INTO unmapped_platform_values (
                                id, mapping_type, source_value, first_task_id,
                                latest_task_id, occurrence_count, status,
                                first_seen_at, last_seen_at
                            ) VALUES (?, ?, ?, ?, ?, 1, 'pending', ?, ?)
                            """,
                            (
                                "unmapped-{}".format(uuid.uuid4().hex), mapping_type,
                                source_value, task_id, task_id, now, now,
                            ),
                        )
                    else:
                        connection.execute(
                            """
                            UPDATE unmapped_platform_values
                            SET latest_task_id = ?, occurrence_count = occurrence_count + 1,
                                status = 'pending', resolved_mapping_id = NULL,
                                resolved_at = NULL, last_seen_at = ?
                            WHERE id = ?
                            """,
                            (task_id, now, existing_unmapped["id"]),
                        )
        mapped_record = dict(record)
        mapped_record["sourceRawValuesJson"] = source_json
        mapped_record["rawValuesJson"] = json.dumps(
            mapped_values, ensure_ascii=False, separators=(",", ":")
        )
        mapped_record["mappingSnapshotJson"] = (
            json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
            if snapshot else None
        )
        mapped_records.append(mapped_record)
    return mapped_records, {
        "appliedMappingCount": len(applied_ids),
        "appliedMappingIds": sorted(applied_ids),
        "pendingValueCount": len(pending_values),
        "pendingRecordCount": pending_record_count,
        "pendingValues": [
            {"mappingType": mapping_type, "sourceValue": source_value}
            for mapping_type, source_value in sorted(pending_values)
        ],
        "existingImportPolicy": "keep_original_mapping_snapshot",
    }


def _validate_rule_parameters(payload):
    parameters = {
        "tolerance_cents": _validate_bounded_int(
            payload.get("toleranceCents"), "金额容差（分）", 0, 100
        ),
        "refund_auto_group_seconds": _validate_bounded_int(
            payload.get("refundAutoGroupSeconds"), "退款自动归组时间", 60, 3600
        ),
        "refund_candidate_seconds": _validate_bounded_int(
            payload.get("refundCandidateSeconds"), "退款候选时间", 61, 259200
        ),
        "settlement_wait_days": _validate_bounded_int(
            payload.get("settlementWaitDays"), "结算等待天数", 1, 90
        ),
    }
    if parameters["refund_candidate_seconds"] <= parameters["refund_auto_group_seconds"]:
        raise ValidationError("退款候选时间必须大于自动归组时间")
    return parameters


def _rule_parameters_from_row(row):
    return {
        "tolerance_cents": row["tolerance_cents"],
        "refund_auto_group_seconds": row["refund_auto_group_seconds"],
        "refund_candidate_seconds": row["refund_candidate_seconds"],
        "settlement_wait_days": row["settlement_wait_days"],
    }


def _rule_parameters_to_api(parameters):
    return {
        "toleranceCents": parameters["tolerance_cents"],
        "refundAutoGroupSeconds": parameters["refund_auto_group_seconds"],
        "refundCandidateSeconds": parameters["refund_candidate_seconds"],
        "settlementWaitDays": parameters["settlement_wait_days"],
    }


def _task_to_api(task):
    return {
        "id": task["id"],
        "entityName": task["entity_name"],
        "storeName": task["store_name"],
        "period": task["period"],
        "status": task["status"],
        "isSample": bool(task["is_sample"]),
        "ruleVersionId": task["rule_version_id"],
        "ruleVersionLabel": task["rule_version_label"],
        "createdAt": task["created_at"],
        "updatedAt": task["updated_at"],
        "completedAt": task["completed_at"],
        "reopenedAt": task["reopened_at"],
    }


def _rule_to_api(rule):
    fixed_cases = json.loads(rule["fixed_case_summary_json"]) \
        if rule.get("fixed_case_summary_json") else None
    return {
        "id": rule["id"],
        "versionLabel": rule["version_label"],
        "toleranceCents": rule["tolerance_cents"],
        "refundAutoGroupSeconds": rule["refund_auto_group_seconds"],
        "refundCandidateSeconds": rule["refund_candidate_seconds"],
        "settlementWaitDays": rule["settlement_wait_days"],
        "status": rule["status"],
        "notes": rule.get("notes"),
        "activatedAt": rule.get("activated_at"),
        "fixedCases": fixed_cases,
        "createdAt": rule["created_at"],
    }


def _rule_draft_to_api(rule):
    if rule is None:
        return None
    fixed_cases = json.loads(rule["last_test_summary_json"]) \
        if rule.get("last_test_summary_json") else None
    return {
        "id": rule["id"],
        "sourceRuleVersionId": rule["source_rule_version_id"],
        "versionLabel": rule["version_label"],
        "toleranceCents": rule["tolerance_cents"],
        "refundAutoGroupSeconds": rule["refund_auto_group_seconds"],
        "refundCandidateSeconds": rule["refund_candidate_seconds"],
        "settlementWaitDays": rule["settlement_wait_days"],
        "notes": rule.get("notes"),
        "status": "draft",
        "lastTestedAt": rule.get("last_tested_at"),
        "lastTestStatus": rule.get("last_test_status"),
        "fixedCases": fixed_cases,
        "createdAt": rule["created_at"],
        "updatedAt": rule["updated_at"],
    }


def _select_task(connection, task_id):
    return connection.execute(
        """
        SELECT t.id, t.entity_name, t.store_name, t.period, t.status, t.rule_version_id,
               t.is_sample,
               r.version_label AS rule_version_label,
               r.tolerance_cents, r.refund_auto_group_seconds,
               r.refund_candidate_seconds, r.settlement_wait_days,
               t.created_at, t.updated_at, t.completed_at, t.reopened_at
        FROM tasks t
        JOIN rule_versions r ON r.id = t.rule_version_id
        WHERE t.id = ?
        """,
        (task_id,),
    ).fetchone()


def _select_file_by_digest(connection, task_id, digest):
    return connection.execute(
        """
        SELECT f.id, f.task_id, f.original_name, f.content_sha256, f.size_bytes,
               f.replacement_reason, f.created_at, f.template_version_id,
               bt.version_label AS template_version_label, bt.name AS template_name,
               i.status AS inspection_status, i.summary_json,
               d.id AS data_import_id,
               d.status AS data_import_status,
               d.summary_json AS data_import_summary_json,
               a.status AS amount_check_status,
               a.summary_json AS amount_check_summary_json,
               a.tolerance_cents AS amount_check_tolerance_cents,
               rr.status AS reconciliation_status,
               rr.summary_json AS reconciliation_summary_json,
               frr.status AS refund_reconciliation_status,
               frr.summary_json AS refund_reconciliation_summary_json,
               srr.status AS supplementary_reconciliation_status,
               srr.summary_json AS supplementary_reconciliation_summary_json
        FROM file_versions f
        JOIN workbook_inspections i ON i.file_version_id = f.id
        LEFT JOIN bill_template_versions bt ON bt.id = f.template_version_id
        LEFT JOIN data_imports d ON d.file_version_id = f.id
        LEFT JOIN amount_check_runs a ON a.import_id = d.id
        LEFT JOIN reconciliation_runs rr ON rr.import_id = d.id
        LEFT JOIN refund_reconciliation_runs frr ON frr.import_id = d.id
        LEFT JOIN supplementary_reconciliation_runs srr
               ON srr.import_id = d.id AND srr.is_current = 1
        WHERE f.task_id = ? AND f.content_sha256 = ?
        LIMIT 1
        """,
        (task_id, digest),
    ).fetchone()


def _select_file_by_id(connection, file_id):
    return connection.execute(
        """
        SELECT f.id, f.task_id, f.original_name, f.content_sha256, f.size_bytes,
               f.replacement_reason, f.created_at, f.template_version_id,
               bt.version_label AS template_version_label, bt.name AS template_name,
               i.status AS inspection_status, i.summary_json,
               d.id AS data_import_id,
               d.status AS data_import_status,
               d.summary_json AS data_import_summary_json,
               a.status AS amount_check_status,
               a.summary_json AS amount_check_summary_json,
               a.tolerance_cents AS amount_check_tolerance_cents,
               rr.status AS reconciliation_status,
               rr.summary_json AS reconciliation_summary_json,
               frr.status AS refund_reconciliation_status,
               frr.summary_json AS refund_reconciliation_summary_json,
               srr.status AS supplementary_reconciliation_status,
               srr.summary_json AS supplementary_reconciliation_summary_json
        FROM file_versions f
        JOIN workbook_inspections i ON i.file_version_id = f.id
        LEFT JOIN bill_template_versions bt ON bt.id = f.template_version_id
        LEFT JOIN data_imports d ON d.file_version_id = f.id
        LEFT JOIN amount_check_runs a ON a.import_id = d.id
        LEFT JOIN reconciliation_runs rr ON rr.import_id = d.id
        LEFT JOIN refund_reconciliation_runs frr ON frr.import_id = d.id
        LEFT JOIN supplementary_reconciliation_runs srr
               ON srr.import_id = d.id AND srr.is_current = 1
        WHERE f.id = ?
        """,
        (file_id,),
    ).fetchone()


def _task_status_for_file(connection, file_id):
    row = connection.execute(
        """
        SELECT i.status AS inspection_status, d.status AS import_status,
               a.status AS amount_status, rr.status AS ordinary_status,
               frr.status AS refund_status, srr.status AS supplementary_status
        FROM file_versions f
        JOIN workbook_inspections i ON i.file_version_id = f.id
        LEFT JOIN data_imports d ON d.file_version_id = f.id
        LEFT JOIN amount_check_runs a ON a.import_id = d.id
        LEFT JOIN reconciliation_runs rr ON rr.import_id = d.id
        LEFT JOIN refund_reconciliation_runs frr ON frr.import_id = d.id
        LEFT JOIN supplementary_reconciliation_runs srr
               ON srr.import_id = d.id AND srr.is_current = 1
        WHERE f.id = ?
        """,
        (file_id,),
    ).fetchone()
    if row is None:
        return "needs_attention"
    attention_flags = (
        row["inspection_status"] != "passed",
        row["import_status"] == "failed",
        row["amount_status"] == "failed",
        row["ordinary_status"] == "needs_attention",
        row["refund_status"] == "needs_attention",
        row["supplementary_status"] == "needs_attention",
    )
    return "needs_attention" if any(attention_flags) else "ready"


def _select_latest_file_id(connection, task_id):
    row = connection.execute(
        """
        SELECT id FROM file_versions
        WHERE task_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    return row["id"] if row is not None else None


def _build_completion_summary(connection, task_id):
    task = _select_task(connection, task_id)
    if task is None:
        raise NotFoundError("没有找到这个对账任务")
    latest = connection.execute(
        """
        SELECT f.id AS file_id, i.status AS inspection_status,
               d.id AS import_id, d.status AS import_status,
               d.blocking_issue_count,
               a.id AS amount_run_id, a.status AS amount_status,
               rr.id AS ordinary_run_id,
               frr.id AS refund_run_id,
               srr.id AS supplementary_run_id
        FROM file_versions f
        JOIN workbook_inspections i ON i.file_version_id = f.id
        LEFT JOIN data_imports d ON d.file_version_id = f.id
        LEFT JOIN amount_check_runs a ON a.import_id = d.id
        LEFT JOIN reconciliation_runs rr ON rr.import_id = d.id
        LEFT JOIN refund_reconciliation_runs frr ON frr.import_id = d.id
        LEFT JOIN supplementary_reconciliation_runs srr
               ON srr.import_id = d.id AND srr.is_current = 1
        WHERE f.task_id = ?
        ORDER BY f.created_at DESC, f.id DESC
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    base = {
        "taskStatus": task["status"],
        "latestFileId": latest["file_id"] if latest is not None else None,
        "ruleVersionId": task["rule_version_id"],
        "ruleVersionLabel": task["rule_version_label"],
        "processingReady": False,
        "blockingIssueCount": 0,
        "systemAttentionCount": 0,
        "resolvedCount": 0,
        "carriedForwardCount": 0,
        "unresolvedCount": 0,
        "manualResolutionCount": 0,
        "unresolvedByType": {},
        "unresolvedPreview": [],
        "requirementsMet": False,
        "canComplete": False,
        "completedAt": task["completed_at"],
        "reopenedAt": task["reopened_at"],
    }
    if latest is None:
        return base

    processing_ready = all((
        latest["inspection_status"] == "passed",
        latest["import_id"] is not None,
        latest["import_status"] != "failed",
        latest["amount_run_id"] is not None,
        latest["amount_status"] == "passed",
        latest["ordinary_run_id"] is not None,
        latest["refund_run_id"] is not None,
        latest["supplementary_run_id"] is not None,
    ))
    attention_rows = []
    if latest["ordinary_run_id"]:
        attention_rows.extend(connection.execute(
            """
            SELECT 'ordinary_settlement' AS result_type, id AS result_id,
                   status AS system_status, primary_identifier
            FROM reconciliation_results
            WHERE run_id = ? AND status != 'matched'
            """,
            (latest["ordinary_run_id"],),
        ).fetchall())
    if latest["refund_run_id"]:
        attention_rows.extend(connection.execute(
            """
            SELECT 'refund_settlement' AS result_type, id AS result_id,
                   status AS system_status, primary_identifier
            FROM refund_reconciliation_results
            WHERE run_id = ? AND status != 'matched'
            """,
            (latest["refund_run_id"],),
        ).fetchall())
    if latest["supplementary_run_id"]:
        attention_statuses = sorted(
            set().union(*(
                config["attention"] for config in SUPPLEMENTARY_RESULT_TYPES.values()
            ))
        )
        placeholders = ",".join("?" for _ in attention_statuses)
        attention_rows.extend(connection.execute(
            """
            SELECT result_type, id AS result_id, status AS system_status,
                   primary_identifier
            FROM supplementary_reconciliation_results
            WHERE run_id = ? AND status IN ({})
            """.format(placeholders),
            (latest["supplementary_run_id"], *attention_statuses),
        ).fetchall())

    manual_rows = connection.execute(
        """
        SELECT * FROM manual_resolution_events
        WHERE task_id = ? AND file_version_id = ? AND is_current = 1
        """,
        (task_id, latest["file_id"]),
    ).fetchall()
    manual_by_result = {
        (row["result_type"], row["result_id"]): row for row in manual_rows
    }
    unresolved = []
    resolved_count = 0
    carried_count = 0
    for item in attention_rows:
        manual = manual_by_result.get((item["result_type"], item["result_id"]))
        if manual is None:
            unresolved.append(item)
        elif manual["resolution_state"] == "carried_forward":
            carried_count += 1
        else:
            resolved_count += 1
    by_type = {}
    for item in unresolved:
        by_type[item["result_type"]] = by_type.get(item["result_type"], 0) + 1
    blocking_count = latest["blocking_issue_count"] or 0
    requirements_met = (
        processing_ready and blocking_count == 0 and not unresolved
    )
    return {
        **base,
        "processingReady": processing_ready,
        "blockingIssueCount": blocking_count,
        "systemAttentionCount": len(attention_rows),
        "resolvedCount": resolved_count,
        "carriedForwardCount": carried_count,
        "unresolvedCount": len(unresolved),
        "manualResolutionCount": len(manual_rows),
        "unresolvedByType": by_type,
        "unresolvedPreview": [
            {
                "resultType": item["result_type"],
                "resultId": item["result_id"],
                "systemStatus": item["system_status"],
                "primaryIdentifier": item["primary_identifier"],
            }
            for item in unresolved[:10]
        ],
        "requirementsMet": requirements_met,
        "canComplete": requirements_met and task["status"] != "completed",
    }


def _get_result_snapshot(connection, task_id, file_id, result_type, result_id):
    if result_type == "ordinary_settlement":
        row = connection.execute(
            """
            SELECT status, settlement_amount_cents AS system_amount_cents,
                   candidate_records_json AS candidates_json
            FROM reconciliation_results
            WHERE task_id = ? AND file_version_id = ? AND id = ?
            """,
            (task_id, file_id, result_id),
        ).fetchone()
        if row is None:
            return None
        candidates = json.loads(row["candidates_json"] or "[]")
        options = [
            {
                "key": item.get("transactionId") or "row:{}".format(item.get("rowNumber")),
                "label": "资金第{}行 · {} · {}".format(
                    item.get("rowNumber") or "—",
                    item.get("transactionId") or "无流水号",
                    _format_cents_label(item.get("amountCents")),
                ),
                "amountCents": item.get("amountCents"),
            }
            for item in candidates
        ]
        return {
            "systemStatus": row["status"],
            "systemAmountCents": row["system_amount_cents"],
            "candidateOptions": options,
        }
    if result_type == "refund_settlement":
        row = connection.execute(
            """
            SELECT status, settlement_amount_cents AS system_amount_cents,
                   candidate_groups_json AS candidates_json
            FROM refund_reconciliation_results
            WHERE task_id = ? AND file_version_id = ? AND id = ?
            """,
            (task_id, file_id, result_id),
        ).fetchone()
        if row is None:
            return None
        groups = json.loads(row["candidates_json"] or "[]")
        options = []
        for index, item in enumerate(groups):
            key = item.get("afterSaleId") or "group:{}".format(index + 1)
            options.append({
                "key": key,
                "label": "售后{} · {}笔资金 · 净额{}".format(
                    item.get("afterSaleId") or "待补编号",
                    item.get("recordCount") or 0,
                    _format_cents_label(item.get("netAmountCents")),
                ),
                "amountCents": item.get("netAmountCents"),
            })
        return {
            "systemStatus": row["status"],
            "systemAmountCents": row["system_amount_cents"],
            "candidateOptions": options,
        }
    row = connection.execute(
        """
        SELECT r.status, COALESCE(r.calculated_amount_cents, r.amount_cents)
                   AS system_amount_cents
        FROM supplementary_reconciliation_results r
        JOIN supplementary_reconciliation_runs srr ON srr.id = r.run_id
        WHERE r.task_id = ? AND r.file_version_id = ?
          AND r.result_type = ? AND r.id = ? AND srr.is_current = 1
        """,
        (task_id, file_id, result_type, result_id),
    ).fetchone()
    if row is None:
        return None
    return {
        "systemStatus": row["status"],
        "systemAmountCents": row["system_amount_cents"],
        "candidateOptions": [],
    }


def _manual_resolution_map(connection, task_id, file_id, result_type, result_ids):
    if not result_ids:
        return {}
    placeholders = ",".join("?" for _ in result_ids)
    rows = connection.execute(
        """
        SELECT * FROM manual_resolution_events
        WHERE task_id = ? AND file_version_id = ? AND result_type = ?
          AND is_current = 1 AND result_id IN ({})
        """.format(placeholders),
        (task_id, file_id, result_type, *result_ids),
    ).fetchall()
    return {row["result_id"]: _manual_resolution_to_api(row) for row in rows}


def _manual_resolution_detail(connection, task_id, file_id, result_type, result_id):
    rows = connection.execute(
        """
        SELECT * FROM manual_resolution_events
        WHERE task_id = ? AND file_version_id = ?
          AND result_type = ? AND result_id = ?
        ORDER BY is_current DESC, created_at DESC, rowid DESC
        """,
        (task_id, file_id, result_type, result_id),
    ).fetchall()
    history = [_manual_resolution_to_api(row) for row in rows]
    current = next((item for item in history if item["isCurrent"]), None)
    return current, history


def _manual_resolution_to_api(row):
    action_labels = {
        "confirm": "人工确认",
        "select_candidate": "人工选择候选",
        "adjust_amount": "人工调整金额",
        "carry_forward": "带到下月",
    }
    state_labels = {
        "resolved": "人工已处理",
        "carried_forward": "已带到下月",
    }
    return {
        "id": row["id"],
        "resultType": "ordinary_settlement",
        "resultType": row["result_type"],
        "resultId": row["result_id"],
        "systemStatus": row["system_status"],
        "resolutionState": row["resolution_state"],
        "resolutionStateLabel": state_labels.get(
            row["resolution_state"], row["resolution_state"]
        ),
        "actionType": row["action_type"],
        "actionLabel": action_labels.get(row["action_type"], row["action_type"]),
        "selectedCandidateKey": row["selected_candidate_key"],
        "adjustedAmountCents": row["adjusted_amount_cents"],
        "followUpDate": row["follow_up_date"],
        "reason": row["reason"],
        "previousEventId": row["previous_event_id"],
        "isCurrent": bool(row["is_current"]),
        "createdAt": row["created_at"],
    }


def _period_event_to_api(row):
    return {
        "id": row["id"],
        "resultType": "refund_settlement",
        "action": row["action"],
        "actionLabel": "完成本期" if row["action"] == "completed" else "重新打开",
        "reason": row["reason"],
        "summary": json.loads(row["summary_json"] or "{}"),
        "ruleVersionId": row["rule_version_id"],
        "createdAt": row["created_at"],
    }


def _format_cents_label(cents):
    if cents is None:
        return "金额缺失"
    value = abs(cents) / 100
    prefix = "-" if cents < 0 else ""
    return "{}¥{:,.2f}".format(prefix, value)


def _select_platform_balance_snapshot(connection, task_id):
    file_row = connection.execute(
        """
        SELECT id, task_id, original_name, stored_name, content_sha256,
               size_bytes, replacement_reason, mapping_version,
               is_simulated_mapping, inspection_status, inspection_json, created_at
        FROM platform_balance_files
        WHERE task_id = ?
        ORDER BY created_at DESC, rowid DESC
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    if file_row is None:
        return None
    snapshot = dict(file_row)
    run_row = connection.execute(
        """
        SELECT id AS run_id, file_id AS run_file_id, rule_version_id,
               mapping_version AS run_mapping_version, enforcement_mode,
               status AS run_status, tolerance_cents, total_result_count,
               matched_count, attention_count, summary_json AS run_summary_json,
               created_at AS run_created_at
        FROM platform_balance_runs
        WHERE task_id = ? AND is_current = 1
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    if run_row is not None:
        snapshot.update(dict(run_row))
    else:
        snapshot.update({
            "run_id": None,
            "run_file_id": None,
            "rule_version_id": None,
            "run_mapping_version": None,
            "enforcement_mode": None,
            "run_status": None,
            "tolerance_cents": None,
            "total_result_count": None,
            "matched_count": None,
            "attention_count": None,
            "run_summary_json": None,
            "run_created_at": None,
        })
    return snapshot


def _platform_balance_snapshot_to_api(snapshot):
    if snapshot is None:
        return None
    inspection = json.loads(snapshot["inspection_json"] or "{}")
    latest_file = {
        "id": snapshot["id"],
        "taskId": snapshot["task_id"],
        "originalName": snapshot["original_name"],
        "contentSha256": snapshot["content_sha256"],
        "sizeBytes": snapshot["size_bytes"],
        "replacementReason": snapshot["replacement_reason"],
        "mappingVersion": snapshot["mapping_version"],
        "isSimulatedMapping": bool(snapshot["is_simulated_mapping"]),
        "inspectionStatus": snapshot["inspection_status"],
        "inspection": inspection,
        "createdAt": snapshot["created_at"],
    }
    run = None
    if snapshot.get("run_id"):
        run = {
            "id": snapshot["run_id"],
            "fileId": snapshot["run_file_id"],
            "ruleVersionId": snapshot["rule_version_id"],
            "mappingVersion": snapshot["run_mapping_version"],
            "enforcementMode": snapshot["enforcement_mode"],
            "status": snapshot["run_status"],
            "toleranceCents": snapshot["tolerance_cents"],
            "totalResultCount": snapshot["total_result_count"],
            "matchedCount": snapshot["matched_count"],
            "attentionCount": snapshot["attention_count"],
            "summary": json.loads(snapshot["run_summary_json"] or "{}"),
            "createdAt": snapshot["run_created_at"],
        }
    return {
        "latestFile": latest_file,
        "run": run,
        "trialMode": True,
        "blockingCompletion": bool(run and run["enforcementMode"] == "blocking"),
        "notice": "当前按模拟字段映射试运行，不影响完成本期；取得抖店真实汇总文件后再启用正式阻断。",
    }


def _platform_balance_result_to_api(row):
    raw_values = json.loads(row["raw_values_json"] or "{}")
    return {
        "id": row["id"],
        "level": row["level"],
        "levelLabel": {"day": "日汇总", "month": "月汇总", "source": "源数据"}.get(
            row["level"], row["level"]
        ),
        "status": row["status"],
        "statusLabel": {
            "matched": "余额核对一致",
            "detail_incomplete": "明细可能不完整",
            "account_period_mismatch": "账户或月份不一致",
            "invalid_source": "源数据无法计算",
        }.get(row["status"], row["status"]),
        "batchKey": row["batch_key"],
        "account": row["account"],
        "periodKey": row["period_key"],
        "summaryCount": row["summary_count"],
        "detailCount": row["detail_count"],
        "summaryIncomeCents": row["summary_income_cents"],
        "detailIncomeCents": row["detail_income_cents"],
        "summaryExpenseCents": row["summary_expense_cents"],
        "detailExpenseCents": row["detail_expense_cents"],
        "openingBalanceCents": row["opening_balance_cents"],
        "closingBalanceCents": row["closing_balance_cents"],
        "calculatedClosingBalanceCents": row["calculated_closing_balance_cents"],
        "differenceCents": row["difference_cents"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
        "explanation": row["explanation"],
        "suggestion": row["suggestion"],
        "source": {
            "sheetName": row["source_sheet"],
            "rowNumber": row["source_row_number"],
            "values": raw_values,
        },
    }


def _select_pending_settlement_snapshot(connection, task_id):
    file_row = connection.execute(
        """
        SELECT id, task_id, original_name, stored_name, content_sha256,
               size_bytes, replacement_reason, mapping_version,
               is_simulated_mapping, inspection_status, inspection_json, created_at
        FROM pending_settlement_files
        WHERE task_id = ?
        ORDER BY created_at DESC, rowid DESC
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    if file_row is None:
        return None
    snapshot = dict(file_row)
    run_row = connection.execute(
        """
        SELECT id AS run_id, file_id AS run_file_id, rule_version_id,
               mapping_version AS run_mapping_version, enforcement_mode,
               status AS run_status, as_of, wait_days, total_result_count,
               attention_count, waiting_count, overdue_count, excluded_count,
               pending_amount_cents, summary_json AS run_summary_json,
               created_at AS run_created_at
        FROM pending_settlement_runs
        WHERE task_id = ? AND is_current = 1
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    if run_row is not None:
        snapshot.update(dict(run_row))
    else:
        snapshot.update({
            "run_id": None,
            "run_file_id": None,
            "rule_version_id": None,
            "run_mapping_version": None,
            "enforcement_mode": None,
            "run_status": None,
            "as_of": None,
            "wait_days": None,
            "total_result_count": None,
            "attention_count": None,
            "waiting_count": None,
            "overdue_count": None,
            "excluded_count": None,
            "pending_amount_cents": None,
            "run_summary_json": None,
            "run_created_at": None,
        })
    return snapshot


def _pending_settlement_snapshot_to_api(snapshot):
    if snapshot is None:
        return None
    inspection = json.loads(snapshot["inspection_json"] or "{}")
    latest_file = {
        "id": snapshot["id"],
        "taskId": snapshot["task_id"],
        "originalName": snapshot["original_name"],
        "contentSha256": snapshot["content_sha256"],
        "sizeBytes": snapshot["size_bytes"],
        "replacementReason": snapshot["replacement_reason"],
        "mappingVersion": snapshot["mapping_version"],
        "isSimulatedMapping": bool(snapshot["is_simulated_mapping"]),
        "inspectionStatus": snapshot["inspection_status"],
        "inspection": inspection,
        "createdAt": snapshot["created_at"],
    }
    run = None
    if snapshot.get("run_id"):
        run = {
            "id": snapshot["run_id"],
            "fileId": snapshot["run_file_id"],
            "ruleVersionId": snapshot["rule_version_id"],
            "mappingVersion": snapshot["run_mapping_version"],
            "enforcementMode": snapshot["enforcement_mode"],
            "status": snapshot["run_status"],
            "asOf": snapshot["as_of"],
            "waitDays": snapshot["wait_days"],
            "totalResultCount": snapshot["total_result_count"],
            "attentionCount": snapshot["attention_count"],
            "waitingCount": snapshot["waiting_count"],
            "overdueCount": snapshot["overdue_count"],
            "excludedCount": snapshot["excluded_count"],
            "pendingAmountCents": snapshot["pending_amount_cents"],
            "summary": json.loads(snapshot["run_summary_json"] or "{}"),
            "createdAt": snapshot["run_created_at"],
        }
    return {
        "latestFile": latest_file,
        "run": run,
        "trialMode": True,
        "blockingCompletion": False,
        "notice": "当前按M018模拟字段映射试运行，不影响完成本期；取得真实待结算文件后再冻结正式映射。",
    }


def _pending_settlement_result_to_api(row):
    raw_values = json.loads(row["raw_values_json"] or "{}")
    auxiliary_values = json.loads(row["aux_raw_values_json"] or "{}")
    status_labels = {
        "waiting": "尚未到预计日期",
        "overdue": "已到预计日期仍未结算",
        "after_sales": "售后处理中",
        "restricted": "平台限制或冻结",
        "insufficient": "资料不足",
        "canceled_refunded": "已取消/退款",
        "settled_excluded": "已进入结算",
        "source_anomaly": "资料异常",
        "invalid_source": "源数据无法分类",
    }
    return {
        "id": row["id"],
        "status": row["status"],
        "statusLabel": status_labels.get(row["status"], row["status"]),
        "isAttention": row["status"] in PENDING_SETTLEMENT_ATTENTION_STATUSES,
        "sceneCode": row["scene_code"],
        "orderId": row["order_id"],
        "suborderId": row["suborder_id"],
        "productId": row["product_id"],
        "paymentCents": row["payment_cents"],
        "orderStatus": row["order_status"],
        "settlementStatus": row["settlement_status"],
        "settlementCycle": row["settlement_cycle"],
        "expectedSettlementAt": row["expected_settlement_at"],
        "expectedSettlementCents": row["expected_settlement_cents"],
        "completedAt": row["completed_at"],
        "afterSalesStatus": row["after_sales_status"],
        "restrictionStatus": row["restriction_status"],
        "enteredSettlement": row["entered_settlement"],
        "recheckAt": row["recheck_at"],
        "completionCondition": row["completion_condition"],
        "sourceType": row["source_type"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
        "explanation": row["explanation"],
        "suggestion": row["suggestion"],
        "source": {
            "sheetName": row["source_sheet"],
            "rowNumber": row["source_row_number"],
            "values": raw_values,
        },
        "auxiliarySource": {
            "sheetName": row["aux_source_sheet"],
            "rowNumber": row["aux_source_row_number"],
            "values": auxiliary_values,
        } if row["aux_source_sheet"] and row["aux_source_row_number"] else None,
    }


def _file_to_api(file_version, database_path=None):
    inspection = json.loads(file_version["summary_json"])
    data_import = None
    if file_version.get("data_import_summary_json"):
        data_import = json.loads(file_version["data_import_summary_json"])
        if database_path:
            with connect(database_path) as connection:
                data_import = enrich_import_summary(
                    connection,
                    file_version.get("data_import_id"),
                    data_import,
                    inspection,
                )
    amount_checks = None
    if file_version.get("amount_check_summary_json"):
        amount_checks = json.loads(file_version["amount_check_summary_json"])
        amount_checks["toleranceCents"] = file_version.get("amount_check_tolerance_cents")
    reconciliation = None
    if file_version.get("reconciliation_summary_json"):
        reconciliation = json.loads(file_version["reconciliation_summary_json"])
    refund_reconciliation = None
    if file_version.get("refund_reconciliation_summary_json"):
        refund_reconciliation = json.loads(file_version["refund_reconciliation_summary_json"])
    supplementary_reconciliation = None
    if file_version.get("supplementary_reconciliation_summary_json"):
        supplementary_reconciliation = json.loads(
            file_version["supplementary_reconciliation_summary_json"]
        )
    return {
        "id": file_version["id"],
        "taskId": file_version["task_id"],
        "originalName": file_version["original_name"],
        "contentSha256": file_version["content_sha256"],
        "sizeBytes": file_version["size_bytes"],
        "replacementReason": file_version["replacement_reason"],
        "createdAt": file_version["created_at"],
        "templateVersionId": file_version.get("template_version_id"),
        "templateVersionLabel": file_version.get("template_version_label"),
        "templateName": file_version.get("template_name"),
        "inspectionStatus": file_version["inspection_status"],
        "inspection": inspection,
        "dataImportStatus": file_version.get("data_import_status"),
        "dataImport": data_import,
        "amountCheckStatus": file_version.get("amount_check_status"),
        "amountChecks": amount_checks,
        "reconciliationStatus": file_version.get("reconciliation_status"),
        "reconciliation": reconciliation,
        "refundReconciliationStatus": file_version.get("refund_reconciliation_status"),
        "refundReconciliation": refund_reconciliation,
        "supplementaryReconciliationStatus": file_version.get("supplementary_reconciliation_status"),
        "supplementaryReconciliation": supplementary_reconciliation,
    }


def _validate_pagination(page, page_size):
    try:
        page = int(page)
        page_size = int(page_size)
    except (TypeError, ValueError):
        raise ValidationError("页码必须是整数")
    if page < 1:
        raise ValidationError("页码必须从1开始")
    if page_size not in (20, 50, 100):
        raise ValidationError("每页条数只支持20、50或100")
    return page, page_size


def _reconciliation_result_to_api(row):
    labels = {
        "matched": "核对一致",
        "missing_fund": "缺少资金记录",
        "amount_mismatch": "金额不一致",
        "multiple_candidates": "多笔候选",
        "not_calculable": "无法计算",
    }
    return {
        "id": row["id"],
        "status": row["status"],
        "statusLabel": labels.get(row["status"], row["status"]),
        "subOrderId": row["primary_identifier"],
        "settlementRowNumber": row["settlement_row_number"],
        "settlementAmountCents": row["settlement_amount_cents"],
        "fundRowNumber": row["fund_row_number"],
        "fundTransactionId": row["fund_primary_identifier"],
        "fundAmountCents": row["fund_amount_cents"],
        "differenceCents": row["difference_cents"],
        "candidateCount": row["candidate_count"],
        "matchedCandidateCount": row["matched_candidate_count"],
        "explanation": row["explanation"],
        "suggestion": row["suggestion"],
    }


def _refund_reconciliation_result_to_api(row):
    labels = {
        "matched": "核对一致",
        "missing_fund": "缺少退款资金",
        "amount_mismatch": "净额不一致",
        "multiple_candidates": "多组候选",
        "outside_auto_window": "超出自动窗口",
        "not_calculable": "无法计算",
    }
    selected_records = json.loads(row.get("selected_records_json") or "[]")
    component_check = json.loads(row.get("component_json") or "{}")
    component_labels = {
        "matched": "构成一致（试算）",
        "mismatch": "构成异常（试算）",
        "limited": "部分构成已核（试算）",
        "missing_evidence": "构成资料不足",
    }
    return {
        "id": row["id"],
        "status": row["status"],
        "statusLabel": labels.get(row["status"], row["status"]),
        "subOrderId": row["primary_identifier"],
        "settlementRowNumber": row["settlement_row_number"],
        "settlementAmountCents": row["settlement_amount_cents"],
        "fundNetAmountCents": row["fund_net_amount_cents"],
        "differenceCents": row["difference_cents"],
        "afterSaleId": row["after_sale_id"],
        "maxTimeDifferenceSeconds": row["max_time_difference_seconds"],
        "candidateCount": row["candidate_count"],
        "candidateGroupCount": row["candidate_group_count"],
        "matchedCandidateCount": row["matched_candidate_count"],
        "selectedRecordCount": len(selected_records),
        "componentStatus": row.get("component_status"),
        "componentStatusLabel": component_check.get("statusLabel")
        or component_labels.get(row.get("component_status"), "未试算"),
        "componentCheck": component_check,
        "explanation": row["explanation"],
        "suggestion": row["suggestion"],
    }


def _supplementary_result_to_api(row):
    labels = {
        "order_found_current": "本次订单已找到",
        "order_found_history": "历史订单已找到",
        "missing_historical_order": "缺少历史订单",
        "missing_order_data": "缺少订单资料",
        "multiple_history_orders": "多条历史订单",
        "settlement_receivable_mismatch": "订单应收与结算不符",
        "settlement_receivable_not_calculable": "订单应收无法计算",
        "settlement_before_refund_review": "结算前退款待核",
        "possibly_unsettled": "可能未结算",
        "order_status_requires_review": "订单状态待核",
        "normal_waiting": "正常等待结算",
        "fully_refunded_no_settlement": "全额退款无需结算",
        "closed_no_settlement": "已关闭无需结算",
        "refund_success": "退款成功",
        "after_sale_closed": "售后关闭",
        "exchange_success": "换货成功",
        "waiting_after_sale": "等待售后处理",
        "new_after_sale_status": "新售后状态",
        "after_sale_refund_conflict": "售后与退款冲突",
        "refund_missing_after_sale": "退款缺少售后单",
        "matched_static_cost": "静态成本已关联",
        "missing_sku": "缺少商品型号",
        "missing_cost": "缺少成本",
        "multiple_cost_candidates": "多条成本候选",
        "not_calculable": "无法计算",
        "classified": "已分类",
        "waiting_classification": "等待分类",
    }
    metadata = json.loads(row.get("metadata_json") or "{}")
    return {
        "id": row["id"],
        "resultType": row["result_type"],
        "status": row["status"],
        "statusLabel": labels.get(row["status"], row["status"]),
        "primaryIdentifier": row["primary_identifier"],
        "sourceRowNumber": row["source_row_number"],
        "linkedRowNumber": row["linked_row_number"],
        "amountCents": row["amount_cents"],
        "calculatedAmountCents": row["calculated_amount_cents"],
        "groupKey": row["group_key"],
        "explanation": row["explanation"],
        "suggestion": row["suggestion"],
        **metadata,
    }


def _source_record_to_api(row):
    return {
        "sourceRecordId": row["id"],
        "sheetName": row["sheet_name"],
        "rowNumber": row["row_number"],
        "primaryIdentifier": row["primary_identifier"],
        "secondaryIdentifier": row["secondary_identifier"],
        "eventTime": row["event_time"],
        "amountCents": row["amount_cents"],
        "values": json.loads(row["raw_values_json"]),
    }


def _source_record_with_context_to_api(row):
    result = _source_record_to_api(row)
    result.update(
        {
            "taskId": row["task_id"],
            "fileId": row["file_version_id"],
            "taskPeriod": row["task_period"],
        }
    )
    return result


def _validate_file_name(value):
    cleaned = clean_text(value, "文件名", 180)
    cleaned = cleaned.replace("\\", "/").split("/")[-1]
    if not cleaned.lower().endswith(".xlsx"):
        raise ValidationError("目前只支持.xlsx文件")
    return cleaned


def _validate_operating_evidence_file_name(value):
    cleaned = clean_text(value, "文件名", 180)
    cleaned = cleaned.replace("\\", "/").split("/")[-1]
    if Path(cleaned).suffix.lower() not in (".xlsx", ".csv"):
        raise ValidationError("经营资料目前只支持.xlsx或.csv文件")
    return cleaned


def _clean_optional_text(value, field_name, max_length):
    if value is None or value == "":
        return None
    return clean_text(value, field_name, max_length)


def _remove_if_present(path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _remove_empty_directory(path):
    try:
        path.rmdir()
    except OSError:
        pass


def _build_operating_report_readiness(
    task,
    latest,
    record_rows,
    supplementary_summary,
    platform_balance,
    pending_settlement,
    operating_evidence,
):
    task_api = _task_to_api(task)
    source = None
    if latest is not None:
        source = {
            "fileId": latest["file_id"],
            "originalName": latest["original_name"],
            "importId": latest["import_id"],
            "importStatus": latest["import_status"],
            "totalRecordCount": latest["total_record_count"] or 0,
            "createdAt": latest["created_at"],
        }

    if latest is None or not latest["import_id"]:
        return {
            "task": task_api,
            "status": "no_import",
            "statusLabel": "尚未导入数据",
            "reportType": "platform_statement_operating_analysis",
            "reportTypeLabel": "平台账单口径经营分析",
            "scopeNotice": "导入账单后才会显示本次可确认金额；不会预置或虚构利润结果。",
            "source": source,
            "summary": {
                "settlementNetCents": None,
                "successfulRefundCents": None,
                "staticCostCents": None,
                "canIssueProfit": False,
            },
            "statement": {"title": "当前可确认金额", "lines": []},
            "evidence": [],
            "operatingEvidence": operating_evidence,
            "completeness": {
                "availableItemCount": 0,
                "partialItemCount": 0,
                "totalItemCount": 8,
                "coveragePercent": 0,
                "canIssueProfit": False,
                "canIssueReconciliationReport": False,
                "blockingItems": _operating_profit_blocking_items(operating_evidence),
            },
            "reports": _operating_report_catalog(False),
        }

    records = [
        {
            "recordType": row["record_type"],
            "values": _json_object(row["values_json"]),
        }
        for row in record_rows
    ]
    settlements = [item for item in records if item["recordType"] == "settlement"]
    after_sales = [item for item in records if item["recordType"] == "after_sale"]
    income = _sum_report_field(settlements, "收入合计")
    expense = _sum_report_field(settlements, "支出合计")
    settlement_net = _sum_report_field(settlements, "结算金额")
    successful_refund = _successful_refund_summary(after_sales)

    formula_difference = None
    formula_consistent = False
    if all(
        item["status"] == "available"
        for item in (income, expense, settlement_net)
    ):
        formula_difference = income["amountCents"] + expense["amountCents"] - settlement_net["amountCents"]
        formula_consistent = abs(formula_difference) <= task["tolerance_cents"]

    costs = (supplementary_summary or {}).get("costs") or {}
    static_cost_cents = costs.get("matchedStaticCostTotalCents")
    static_cost_count = costs.get("matchedCount") or 0
    static_cost_status = "partial" if static_cost_count and static_cost_cents is not None else "missing"
    settlement_status = settlement_net["status"]
    if settlement_status == "available" and formula_difference is not None and not formula_consistent:
        settlement_status = "needs_attention"

    platform_balance_status = "partial" if platform_balance and platform_balance.get("run_id") else "missing"
    pending_settlement_status = "partial" if pending_settlement and pending_settlement.get("run_id") else "missing"
    operating_evidence_by_type = {
        item["code"]: item for item in operating_evidence.get("categories", [])
    }
    erp_category = operating_evidence_by_type.get("erp_cost", {})
    fulfillment_category = operating_evidence_by_type.get("fulfillment_expense", {})
    operating_expense_category = operating_evidence_by_type.get("operating_expense", {})
    erp_cost_received = bool(erp_category.get("latestFile"))
    fulfillment_received = bool(fulfillment_category.get("latestFile"))
    operating_expense_received = bool(operating_expense_category.get("latestFile"))
    erp_run = erp_category.get("run") or {}
    fulfillment_run = fulfillment_category.get("run") or {}
    operating_expense_run = operating_expense_category.get("run") or {}
    erp_trial_passed = erp_run.get("status") == "passed"
    fulfillment_trial_passed = fulfillment_run.get("status") == "passed"
    operating_expense_trial_passed = operating_expense_run.get("status") == "passed"
    evidence = [
        _report_evidence(
            "platform_settlement",
            "平台结算口径",
            settlement_status,
            "结算账单可计算收入、支出和结算净额。",
        ),
        _report_evidence(
            "successful_refund",
            "退款规模",
            successful_refund["status"],
            "只统计最终状态为退款成功的售后记录。",
        ),
        _report_evidence(
            "static_cost",
            "订单静态成本",
            static_cost_status,
            "当前成本表没有生效日期和退货成本冲回，只能试算。",
        ),
        _report_evidence(
            "platform_balance",
            "平台资金完整性",
            platform_balance_status,
            "已导入时仍是模拟映射，真实日/月汇总表头未冻结。",
        ),
        _report_evidence(
            "pending_settlement",
            "待结算跟踪",
            pending_settlement_status,
            "已导入时仍是模拟映射，不能当作正式期末应收。",
        ),
        _report_evidence(
            "cost_reversal",
            "退货入库与成本冲回",
            "available" if erp_trial_passed else ("partial" if erp_cost_received else "missing"),
            (
                "模拟ERP成本和退货冲回已完成匹配，仅用于试算。"
                if erp_trial_passed
                else "ERP资料已收到，尚待字段映射、成本生效和退货冲回口径确认。"
                if erp_cost_received
                else "尚未收到ERP历史出库成本和退货入库资料。"
            ),
        ),
        _report_evidence(
            "fulfillment_expense",
            "快递与仓储费用",
            "available" if fulfillment_trial_passed else ("partial" if fulfillment_received else "missing"),
            (
                "模拟快递和仓储费已完成子订单匹配，仅用于试算。"
                if fulfillment_trial_passed
                else "履约费用资料已收到，尚待字段映射、运单匹配和计价口径确认。"
                if fulfillment_received
                else "尚未收到快递月账单、运单和计价资料。"
            ),
        ),
        _report_evidence(
            "operating_expense",
            "投流、线下及管理费用",
            "available" if operating_expense_trial_passed else ("partial" if operating_expense_received else "missing"),
            (
                "模拟经营费用已按店铺归属和分摊方式进入试算。"
                if operating_expense_trial_passed
                else "经营费用资料已收到，尚待字段映射、店铺归属和分摊口径确认。"
                if operating_expense_received
                else "尚未收到月度经营费用及分摊资料。"
            ),
        ),
    ]
    available_count = sum(item["status"] == "available" for item in evidence)
    partial_count = sum(item["status"] in ("partial", "needs_attention") for item in evidence)
    coverage_percent = round((available_count + partial_count * 0.5) / len(evidence) * 100)

    trial_ready = bool(
        task_api.get("isSample")
        and formula_consistent
        and settlement_status == "available"
        and erp_trial_passed
        and fulfillment_trial_passed
        and operating_expense_trial_passed
    )
    erp_net_cost_cents = erp_run.get("totalAmountCents") if erp_trial_passed else None
    fulfillment_expense_cents = (
        fulfillment_run.get("totalAmountCents") if fulfillment_trial_passed else None
    )
    operating_expense_cents = (
        operating_expense_run.get("totalAmountCents") if operating_expense_trial_passed else None
    )
    trial_profit_cents = None
    if trial_ready:
        trial_profit_cents = (
            settlement_net["amountCents"]
            - erp_net_cost_cents
            - fulfillment_expense_cents
            - operating_expense_cents
        )

    lines = [
        _report_line(
            "settlement_income",
            "结算收入",
            income["amountCents"],
            income["status"],
            "结算账单 · 收入合计",
            "平台本次结算确认的收入项合计。",
        ),
        _report_line(
            "settlement_expense",
            "平台结算支出",
            expense["amountCents"],
            expense["status"],
            "结算账单 · 支出合计",
            "包含账单中已列示的平台服务费、佣金和分成等。",
        ),
        _report_line(
            "settlement_net",
            "平台结算净额（不是利润）",
            settlement_net["amountCents"],
            settlement_status,
            "结算账单 · 结算金额",
            (
                "收入加支出与结算净额一致。"
                if formula_consistent
                else "收入、支出与结算净额尚未完成一致性确认。"
            ),
        ),
        _report_line(
            "successful_refund",
            "退款成功金额",
            successful_refund["amountCents"],
            successful_refund["status"],
            "售后表 · 退款成功",
            "用于解释退款规模；不从已包含退款的结算净额中重复扣减。",
        ),
        _report_line(
            "static_cost",
            "当前关联静态成本",
            static_cost_cents,
            static_cost_status,
            "订单明细 + 成本表",
            "仅供练习测算；不直接扣减为当期利润。",
        ),
        _report_line(
            "operating_profit",
            "店铺经营利润（模拟试算）" if trial_ready else "店铺经营利润",
            trial_profit_cents,
            "available" if trial_ready else "blocked",
            "平台结算 + 三类模拟资料" if trial_ready else "待补齐多类资料",
            (
                "仅验证数据映射、成本冲回和利润公式；不能用于经营决策或会计出表。"
                if trial_ready
                else "关键成本和费用未齐，当前不计算，避免给出虚假利润。"
            ),
        ),
    ]
    can_issue_reconciliation = settlement_net["status"] == "available" and formula_consistent
    profit_trial = None
    if trial_ready:
        profit_trial = {
            "status": "available",
            "statusLabel": "模拟试算已生成",
            "dataMode": "simulated_trial",
            "title": "店铺经营利润模拟试算",
            "formula": "平台结算净额 - ERP净销售成本 - 履约费用 - 经营费用",
            "amountCents": trial_profit_cents,
            "lines": [
                {"code": "settlement_net", "label": "平台结算净额", "effectCents": settlement_net["amountCents"], "source": "结算账单"},
                {"code": "net_sales_cost", "label": "ERP净销售成本", "effectCents": -erp_net_cost_cents, "source": "ERP成本退货 · {}".format(erp_run.get("mappingVersion"))},
                {"code": "fulfillment_expense", "label": "快递与仓储费用", "effectCents": -fulfillment_expense_cents, "source": "快递仓储费用 · {}".format(fulfillment_run.get("mappingVersion"))},
                {"code": "operating_expense", "label": "投流、线下及管理费用", "effectCents": -operating_expense_cents, "source": "经营费用 · {}".format(operating_expense_run.get("mappingVersion"))},
                {"code": "trial_operating_profit", "label": "模拟经营利润", "effectCents": trial_profit_cents, "source": "试算公式"},
            ],
            "notice": "全部外部成本和费用均为造数，仅验证产品流程。退款已体现在平台结算净额中，未再重复扣减。",
        }
    return {
        "task": task_api,
        "status": "trial_ready" if trial_ready else "data_pending",
        "statusLabel": "模拟利润试算已生成" if trial_ready else "账单金额可看，利润资料待补",
        "reportType": "platform_statement_operating_analysis",
        "reportTypeLabel": "平台账单口径经营分析",
        "scopeNotice": (
            "已生成的利润是模拟资料试算，只验证产品链路和公式，不等同于真实经营利润或正式会计利润。"
            if trial_ready
            else "当前只展示已有账单能证明的金额，不等同于店铺经营利润，更不等同于正式会计利润。"
        ),
        "source": source,
        "summary": {
            "settlementIncomeCents": income["amountCents"],
            "settlementExpenseCents": expense["amountCents"],
            "settlementNetCents": settlement_net["amountCents"],
            "successfulRefundCents": successful_refund["amountCents"],
            "successfulRefundCount": successful_refund["recordCount"],
            "staticCostCents": static_cost_cents,
            "staticCostOrderCount": static_cost_count,
            "settlementFormulaDifferenceCents": formula_difference,
            "settlementFormulaConsistent": formula_consistent,
            "canIssueProfit": False,
            "canIssueTrialProfit": trial_ready,
            "trialOperatingProfitCents": trial_profit_cents,
        },
        "statement": {"title": "当前可确认金额", "lines": lines},
        "profitTrial": profit_trial,
        "evidence": evidence,
        "operatingEvidence": operating_evidence,
        "completeness": {
            "availableItemCount": available_count,
            "partialItemCount": partial_count,
            "totalItemCount": len(evidence),
            "coveragePercent": coverage_percent,
            "canIssueProfit": False,
            "canIssueTrialProfit": trial_ready,
            "canIssueReconciliationReport": can_issue_reconciliation,
            "blockingItems": _operating_profit_blocking_items(operating_evidence),
        },
        "reports": _operating_report_catalog(can_issue_reconciliation, trial_ready),
    }


def _sum_report_field(records, field_name):
    parsed_values = []
    invalid_count = 0
    for record in records:
        value = record["values"].get(field_name)
        cents, error = parse_money_or_number(value, cents=True)
        if error:
            invalid_count += 1
        else:
            parsed_values.append(cents)
    if parsed_values and invalid_count == 0:
        status = "available"
    elif parsed_values:
        status = "partial"
    else:
        status = "missing"
    return {
        "amountCents": sum(parsed_values) if parsed_values else None,
        "status": status,
        "recordCount": len(parsed_values),
        "invalidCount": invalid_count,
    }


def _successful_refund_summary(after_sales):
    if not after_sales:
        return {"amountCents": None, "status": "missing", "recordCount": 0}
    successful = [
        item for item in after_sales
        if "退款成功" in str(item["values"].get("售后状态") or "")
    ]
    total = 0
    invalid_count = 0
    for item in successful:
        goods, goods_error = parse_money_or_number(
            item["values"].get("退商品金额（元）"), cents=True
        )
        shipping, shipping_error = parse_money_or_number(
            item["values"].get("退运费金额（元）"), cents=True
        )
        if goods_error and shipping_error:
            invalid_count += 1
            continue
        total += (goods or 0) + (shipping or 0)
    if not successful:
        return {"amountCents": 0, "status": "available", "recordCount": 0}
    status = "available" if invalid_count == 0 else ("partial" if invalid_count < len(successful) else "missing")
    return {
        "amountCents": total if status != "missing" else None,
        "status": status,
        "recordCount": len(successful) - invalid_count,
    }


def _report_line(code, label, amount_cents, status, source_label, note):
    return {
        "code": code,
        "label": label,
        "amountCents": amount_cents,
        "status": status,
        "statusLabel": _report_status_label(status),
        "sourceLabel": source_label,
        "note": note,
    }


def _report_evidence(code, label, status, note):
    return {
        "code": code,
        "label": label,
        "status": status,
        "statusLabel": _report_status_label(status),
        "note": note,
    }


def _report_status_label(status):
    return {
        "available": "可使用",
        "partial": "部分可用",
        "missing": "缺少资料",
        "needs_attention": "需检查",
        "blocked": "暂不计算",
    }.get(status, status)


def _select_operating_evidence_rows(connection, task_id):
    return connection.execute(
        """
        SELECT f.*, f.rowid AS file_rowid,
               r.id AS run_id,
               r.mapping_version AS run_mapping_version,
               r.data_mode AS run_data_mode,
               r.status AS run_status,
               r.total_row_count AS run_total_row_count,
               r.matched_row_count AS run_matched_row_count,
               r.attention_count AS run_attention_count,
               r.total_amount_cents AS run_total_amount_cents,
               r.summary_json AS run_summary_json,
               r.is_current AS run_is_current,
               r.created_at AS run_created_at
        FROM operating_evidence_files f
        LEFT JOIN operating_evidence_runs r ON r.file_id = f.id
        WHERE f.task_id = ?
        ORDER BY f.evidence_type, f.created_at DESC, f.rowid DESC
        """,
        (task_id,),
    ).fetchall()


def _operating_evidence_run_to_api(row):
    if row is None:
        return None
    data = row_to_dict(row)
    run_id = data.get("run_id") or data.get("id")
    return {
        "id": run_id,
        "mappingVersion": data.get("run_mapping_version") or data.get("mapping_version"),
        "dataMode": data.get("run_data_mode") or data.get("data_mode"),
        "status": data.get("run_status") or data.get("status"),
        "statusLabel": {
            "passed": "模拟试算完成",
            "needs_attention": "模拟数据需检查",
            "failed": "试算失败",
        }.get(data.get("run_status") or data.get("status"), "待处理"),
        "totalRowCount": data.get("run_total_row_count") if "run_total_row_count" in data else data.get("total_row_count"),
        "matchedRowCount": data.get("run_matched_row_count") if "run_matched_row_count" in data else data.get("matched_row_count"),
        "attentionCount": data.get("run_attention_count") if "run_attention_count" in data else data.get("attention_count"),
        "totalAmountCents": data.get("run_total_amount_cents") if "run_total_amount_cents" in data else data.get("total_amount_cents"),
        "summary": _json_object(data.get("run_summary_json") or data.get("summary_json")),
        "isCurrent": bool(data.get("run_is_current") if "run_is_current" in data else data.get("is_current")),
        "createdAt": data.get("run_created_at") or data.get("created_at"),
        "originalName": data.get("original_name"),
    }


def _operating_evidence_row_to_api(row):
    data = row_to_dict(row)
    return {
        "id": data["id"],
        "sheetName": data["sheet_name"],
        "rowNumber": data["row_number"],
        "primaryIdentifier": data["primary_identifier"],
        "secondaryIdentifier": data["secondary_identifier"],
        "status": data["status"],
        "statusLabel": "已匹配" if data["status"] == "matched" else "需检查",
        "amountCents": data["amount_cents"],
        "details": _json_object(data["details_json"]),
        "rawValues": _json_object(data["raw_values_json"]),
        "explanation": data["explanation"],
    }


def _build_operating_evidence_catalog(rows):
    grouped = {code: [] for code in OPERATING_EVIDENCE_TYPES}
    for row in rows or []:
        row_data = row_to_dict(row)
        if row_data.get("evidence_type") in grouped:
            grouped[row_data["evidence_type"]].append(row_data)
    categories = []
    for code, definition in OPERATING_EVIDENCE_TYPES.items():
        versions = grouped[code]
        latest = versions[0] if versions else None
        current_run_row = next(
            (
                item for item in versions
                if item.get("run_id") and item.get("run_is_current") == 1
            ),
            None,
        )
        current_run = (
            _operating_evidence_run_to_api(current_run_row)
            if current_run_row else None
        )
        if current_run is not None:
            status = current_run["status"]
            status_label = current_run["statusLabel"]
        else:
            status = "received_pending_mapping" if latest else "missing"
            status_label = "已收到，待映射" if latest else "待提交"
        categories.append(
            {
                "code": code,
                **definition,
                "acceptedFormats": [".xlsx", ".csv"],
                "maxSizeMb": 50,
                "versionCount": len(versions),
                "status": status,
                "statusLabel": status_label,
                "run": current_run,
                "latestFile": (
                    {
                        "id": latest["id"],
                        "originalName": latest["original_name"],
                        "sizeBytes": latest["size_bytes"],
                        "replacementReason": latest["replacement_reason"],
                        "processingStatus": latest["processing_status"],
                        "createdAt": latest["created_at"],
                    }
                    if latest
                    else None
                ),
            }
        )
    received_count = sum(bool(item["latestFile"]) for item in categories)
    processed_count = sum(bool(item["run"]) for item in categories)
    passed_count = sum(
        bool(item["run"] and item["run"]["status"] == "passed")
        for item in categories
    )
    return {
        "receivedTypeCount": received_count,
        "processedTypeCount": processed_count,
        "passedTypeCount": passed_count,
        "totalTypeCount": len(categories),
        "allFilesReceived": received_count == len(categories),
        "mappingComplete": passed_count == len(categories),
        "canCalculateProfit": passed_count == len(categories),
        "scopeNotice": (
            "三类模拟资料已通过试算映射；只用于验证流程和计算，不能作为真实经营或会计结论。"
            if passed_count == len(categories)
            else "文件已收到只代表资料留存成功；字段映射、业务口径和重复检查完成前，不进入利润计算。"
        ),
        "categories": categories,
    }


def _operating_profit_blocking_items(operating_evidence=None):
    evidence_by_task = {
        item["taskId"]: item
        for item in (operating_evidence or {}).get("categories", [])
    }
    items = [
        {"taskId": "M017-B", "label": "平台资金日/月汇总正式映射", "unlock": "确认账单收支和期末资金完整性", "status": "pending"},
        {"taskId": "M018-B", "label": "待结算订单正式映射", "unlock": "确认未结算收入和期末应收", "status": "pending"},
        {"taskId": "M019-B", "label": "完整资金分类及扣回/返还", "unlock": "区分平台费用、其他收入和其他支出", "status": "pending"},
        {"taskId": "M020", "label": "ERP历史成本与退货成本冲回", "unlock": "生成可归属当期的销售成本", "status": "pending"},
        {"taskId": "M021", "label": "快递、仓储账单与分摊", "unlock": "补齐履约费用", "status": "pending"},
        {"taskId": "M022-B", "label": "投流、线下及管理费用导入", "unlock": "补齐店铺经营费用并生成试算利润", "status": "pending"},
    ]
    for item in items:
        received = evidence_by_task.get(item["taskId"])
        if received and received.get("run") and received["run"].get("status") == "passed":
            item["status"] = "trial_passed"
            item["statusLabel"] = "模拟试算通过"
            item["fileName"] = received["latestFile"]["originalName"]
        elif received and received.get("latestFile"):
            item["status"] = "received_pending_mapping"
            item["statusLabel"] = "已收到，待映射"
            item["fileName"] = received["latestFile"]["originalName"]
        else:
            item["statusLabel"] = "Pending"
            item["fileName"] = None
    return items


def _operating_report_catalog(can_issue_reconciliation, can_issue_trial_profit=False):
    return [
        {
            "code": "reconciliation_detail",
            "label": "对账结果明细",
            "status": "available" if can_issue_reconciliation else "pending",
            "statusLabel": "可导出" if can_issue_reconciliation else "待对账通过",
            "description": "统一宽表，可按状态、场景和编号筛选后导出。",
        },
        {
            "code": "operating_readiness",
            "label": "经营报表准备度",
            "status": "available",
            "statusLabel": "可查看",
            "description": "展示当前可信金额、缺失资料和解锁路径。",
        },
        {
            "code": "store_operating_profit",
            "label": "店铺月度经营利润模拟试算" if can_issue_trial_profit else "店铺月度经营利润表",
            "status": "available" if can_issue_trial_profit else "pending",
            "statusLabel": "模拟可查看" if can_issue_trial_profit else "资料待补",
            "description": (
                "已用明确标识的造数打通成本、履约费和经营费穿透，不作为正式出表。"
                if can_issue_trial_profit
                else "M022-B：成本和费用齐备后生成，每个数字可穿透到明细。"
            ),
        },
        {
            "code": "report_center",
            "label": "经营报表中心",
            "status": "planned",
            "statusLabel": "已规划",
            "description": "M023：提供月度趋势、对比、导出和指标穿透。",
        },
        {
            "code": "formal_accounting_profit",
            "label": "正式会计利润表",
            "status": "out_of_scope",
            "statusLabel": "不在当前范围",
            "description": "需要总账、税务、权责期调整和凭证体系，不由平台账单直接产出。",
        },
    ]


def _json_object(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
