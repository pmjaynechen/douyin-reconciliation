import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .configuration_catalog import (
    DEFAULT_PLATFORM_VALUE_MAPPINGS,
    DEFAULT_TEMPLATE_CODE,
    DEFAULT_TEMPLATE_ID,
    DEFAULT_TEMPLATE_SHEETS,
    VALUE_MAPPING_TYPES,
)

SCHEMA_VERSION = 19


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect(database_path):
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database_path), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def initialize_database(database_path):
    with connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                entity_name TEXT NOT NULL CHECK(length(entity_name) BETWEEN 1 AND 100),
                store_name TEXT NOT NULL CHECK(length(store_name) BETWEEN 1 AND 100),
                period TEXT NOT NULL CHECK(length(period) = 7),
                status TEXT NOT NULL CHECK(status IN (
                    'draft', 'checking_files', 'ready', 'reconciling',
                    'needs_attention', 'completed', 'reopened', 'failed'
                )),
                rule_version_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                reopened_at TEXT,
                UNIQUE(entity_name, store_name, period)
            );

            CREATE TABLE IF NOT EXISTS rule_versions (
                id TEXT PRIMARY KEY,
                version_label TEXT NOT NULL UNIQUE,
                tolerance_cents INTEGER NOT NULL CHECK(tolerance_cents >= 0),
                refund_auto_group_seconds INTEGER NOT NULL CHECK(refund_auto_group_seconds > 0),
                refund_candidate_seconds INTEGER NOT NULL CHECK(refund_candidate_seconds > 0),
                settlement_wait_days INTEGER NOT NULL CHECK(settlement_wait_days > 0),
                status TEXT NOT NULL CHECK(status IN ('current', 'inactive')),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS file_versions (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                replacement_reason TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(task_id, content_sha256)
            );

            CREATE TABLE IF NOT EXISTS operation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
                action TEXT NOT NULL,
                reason TEXT,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_period ON tasks(period DESC, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_operation_logs_task ON operation_logs(task_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_file_versions_task ON file_versions(task_id, created_at DESC);
            """
        )

        version_one = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 1"
        ).fetchone()
        if not version_one:
            now = utc_now()
            connection.execute(
                """
                INSERT OR IGNORE INTO rule_versions (
                    id, version_label, tolerance_cents, refund_auto_group_seconds,
                    refund_candidate_seconds, settlement_wait_days, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'current', ?)
                """,
                ("rule-v1", "V1.0", 1, 300, 86400, 7, now),
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (1, now),
            )

        version_two = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 2"
        ).fetchone()
        if not version_two:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS workbook_inspections (
                    id TEXT PRIMARY KEY,
                    file_version_id TEXT NOT NULL UNIQUE
                        REFERENCES file_versions(id) ON DELETE CASCADE,
                    status TEXT NOT NULL CHECK(status IN ('passed', 'failed')),
                    sheet_count INTEGER NOT NULL CHECK(sheet_count >= 0),
                    required_sheet_count INTEGER NOT NULL CHECK(required_sheet_count >= 0),
                    found_required_sheet_count INTEGER NOT NULL CHECK(found_required_sheet_count >= 0),
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_workbook_inspections_status
                    ON workbook_inspections(status, created_at DESC);
                """
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (2, utc_now()),
            )

        version_three = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 3"
        ).fetchone()
        if not version_three:
            connection.execute(
                "ALTER TABLE tasks ADD COLUMN is_sample INTEGER NOT NULL DEFAULT 0 CHECK(is_sample IN (0, 1))"
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (3, utc_now()),
            )

        version_four = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 4"
        ).fetchone()
        if not version_four:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS data_imports (
                    id TEXT PRIMARY KEY,
                    file_version_id TEXT NOT NULL UNIQUE
                        REFERENCES file_versions(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    status TEXT NOT NULL CHECK(status IN ('passed', 'warning', 'failed')),
                    total_record_count INTEGER NOT NULL CHECK(total_record_count >= 0),
                    blocking_issue_count INTEGER NOT NULL CHECK(blocking_issue_count >= 0),
                    warning_issue_count INTEGER NOT NULL CHECK(warning_issue_count >= 0),
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS source_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    import_id TEXT NOT NULL REFERENCES data_imports(id) ON DELETE CASCADE,
                    file_version_id TEXT NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    sheet_name TEXT NOT NULL,
                    row_number INTEGER NOT NULL CHECK(row_number > 0),
                    record_type TEXT NOT NULL,
                    primary_identifier TEXT,
                    secondary_identifier TEXT,
                    event_time TEXT,
                    amount_cents INTEGER,
                    raw_values_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(file_version_id, sheet_name, row_number)
                );

                CREATE TABLE IF NOT EXISTS data_issues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    import_id TEXT NOT NULL REFERENCES data_imports(id) ON DELETE CASCADE,
                    file_version_id TEXT NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    severity TEXT NOT NULL CHECK(severity IN ('blocking', 'warning')),
                    code TEXT NOT NULL,
                    sheet_name TEXT NOT NULL,
                    row_number INTEGER,
                    field_name TEXT,
                    raw_value TEXT,
                    message TEXT NOT NULL,
                    suggestion TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_data_imports_task
                    ON data_imports(task_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_source_records_task_type
                    ON source_records(task_id, record_type, primary_identifier);
                CREATE INDEX IF NOT EXISTS idx_data_issues_task_severity
                    ON data_issues(task_id, severity, sheet_name, row_number);
                """
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (4, utc_now()),
            )

        version_five = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 5"
        ).fetchone()
        if not version_five:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS amount_check_runs (
                    id TEXT PRIMARY KEY,
                    import_id TEXT NOT NULL UNIQUE REFERENCES data_imports(id) ON DELETE CASCADE,
                    file_version_id TEXT NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    rule_version_id TEXT NOT NULL REFERENCES rule_versions(id),
                    status TEXT NOT NULL CHECK(status IN ('passed', 'failed')),
                    total_check_count INTEGER NOT NULL CHECK(total_check_count >= 0),
                    passed_count INTEGER NOT NULL CHECK(passed_count >= 0),
                    failed_count INTEGER NOT NULL CHECK(failed_count >= 0),
                    not_calculable_count INTEGER NOT NULL CHECK(not_calculable_count >= 0),
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS amount_check_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES amount_check_runs(id) ON DELETE CASCADE,
                    import_id TEXT NOT NULL REFERENCES data_imports(id) ON DELETE CASCADE,
                    file_version_id TEXT NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    sheet_name TEXT NOT NULL,
                    row_number INTEGER NOT NULL CHECK(row_number > 0),
                    record_type TEXT NOT NULL,
                    primary_identifier TEXT,
                    check_code TEXT NOT NULL,
                    check_label TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('passed', 'failed', 'not_calculable')),
                    source_amount_cents INTEGER,
                    calculated_amount_cents INTEGER,
                    difference_cents INTEGER,
                    message TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, sheet_name, row_number, check_code)
                );

                CREATE INDEX IF NOT EXISTS idx_amount_check_runs_task
                    ON amount_check_runs(task_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_amount_check_results_status
                    ON amount_check_results(task_id, status, check_code, row_number);
                """
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (5, utc_now()),
            )

        version_six = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 6"
        ).fetchone()
        if not version_six:
            connection.execute(
                "ALTER TABLE amount_check_runs ADD COLUMN tolerance_cents INTEGER CHECK(tolerance_cents >= 0)"
            )
            connection.execute(
                """
                UPDATE amount_check_runs
                SET tolerance_cents = (
                    SELECT r.tolerance_cents
                    FROM rule_versions r
                    WHERE r.id = amount_check_runs.rule_version_id
                )
                WHERE tolerance_cents IS NULL
                """
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (6, utc_now()),
            )

        version_seven = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 7"
        ).fetchone()
        if not version_seven:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS reconciliation_runs (
                    id TEXT PRIMARY KEY,
                    import_id TEXT NOT NULL UNIQUE REFERENCES data_imports(id) ON DELETE CASCADE,
                    file_version_id TEXT NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    rule_version_id TEXT NOT NULL REFERENCES rule_versions(id),
                    result_type TEXT NOT NULL CHECK(result_type = 'ordinary_settlement'),
                    status TEXT NOT NULL CHECK(status IN ('passed', 'needs_attention')),
                    total_result_count INTEGER NOT NULL CHECK(total_result_count >= 0),
                    matched_count INTEGER NOT NULL CHECK(matched_count >= 0),
                    attention_count INTEGER NOT NULL CHECK(attention_count >= 0),
                    settlement_amount_total_cents INTEGER NOT NULL,
                    matched_fund_amount_total_cents INTEGER NOT NULL,
                    difference_total_cents INTEGER NOT NULL,
                    tolerance_cents INTEGER NOT NULL CHECK(tolerance_cents >= 0),
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reconciliation_results (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES reconciliation_runs(id) ON DELETE CASCADE,
                    import_id TEXT NOT NULL REFERENCES data_imports(id) ON DELETE CASCADE,
                    file_version_id TEXT NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    result_type TEXT NOT NULL CHECK(result_type = 'ordinary_settlement'),
                    status TEXT NOT NULL CHECK(status IN (
                        'matched', 'missing_fund', 'amount_mismatch',
                        'multiple_candidates', 'not_calculable'
                    )),
                    primary_identifier TEXT,
                    settlement_record_id INTEGER NOT NULL REFERENCES source_records(id) ON DELETE CASCADE,
                    settlement_row_number INTEGER NOT NULL CHECK(settlement_row_number > 0),
                    settlement_amount_cents INTEGER,
                    fund_record_id INTEGER REFERENCES source_records(id) ON DELETE SET NULL,
                    fund_row_number INTEGER,
                    fund_primary_identifier TEXT,
                    fund_amount_cents INTEGER,
                    difference_cents INTEGER,
                    candidate_count INTEGER NOT NULL CHECK(candidate_count >= 0),
                    matched_candidate_count INTEGER NOT NULL CHECK(matched_candidate_count >= 0),
                    candidate_records_json TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    suggestion TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, settlement_record_id, result_type)
                );

                CREATE INDEX IF NOT EXISTS idx_reconciliation_runs_task
                    ON reconciliation_runs(task_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_reconciliation_results_filter
                    ON reconciliation_results(run_id, status, settlement_row_number);
                CREATE INDEX IF NOT EXISTS idx_reconciliation_results_identifier
                    ON reconciliation_results(task_id, primary_identifier);
                """
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (7, utc_now()),
            )

        version_eight = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 8"
        ).fetchone()
        if not version_eight:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS refund_reconciliation_runs (
                    id TEXT PRIMARY KEY,
                    import_id TEXT NOT NULL UNIQUE REFERENCES data_imports(id) ON DELETE CASCADE,
                    file_version_id TEXT NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    rule_version_id TEXT NOT NULL REFERENCES rule_versions(id),
                    result_type TEXT NOT NULL CHECK(result_type = 'refund_settlement'),
                    status TEXT NOT NULL CHECK(status IN ('passed', 'needs_attention')),
                    total_result_count INTEGER NOT NULL CHECK(total_result_count >= 0),
                    matched_count INTEGER NOT NULL CHECK(matched_count >= 0),
                    attention_count INTEGER NOT NULL CHECK(attention_count >= 0),
                    settlement_amount_total_cents INTEGER NOT NULL,
                    matched_fund_amount_total_cents INTEGER NOT NULL,
                    difference_total_cents INTEGER NOT NULL,
                    tolerance_cents INTEGER NOT NULL CHECK(tolerance_cents >= 0),
                    auto_group_seconds INTEGER NOT NULL CHECK(auto_group_seconds > 0),
                    candidate_seconds INTEGER NOT NULL CHECK(candidate_seconds > 0),
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS refund_reconciliation_results (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES refund_reconciliation_runs(id) ON DELETE CASCADE,
                    import_id TEXT NOT NULL REFERENCES data_imports(id) ON DELETE CASCADE,
                    file_version_id TEXT NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    status TEXT NOT NULL CHECK(status IN (
                        'matched', 'missing_fund', 'amount_mismatch',
                        'multiple_candidates', 'outside_auto_window', 'not_calculable'
                    )),
                    primary_identifier TEXT,
                    settlement_record_id INTEGER NOT NULL REFERENCES source_records(id) ON DELETE CASCADE,
                    settlement_row_number INTEGER NOT NULL CHECK(settlement_row_number > 0),
                    settlement_amount_cents INTEGER,
                    fund_net_amount_cents INTEGER,
                    difference_cents INTEGER,
                    after_sale_id TEXT,
                    max_time_difference_seconds INTEGER,
                    candidate_count INTEGER NOT NULL CHECK(candidate_count >= 0),
                    candidate_group_count INTEGER NOT NULL CHECK(candidate_group_count >= 0),
                    matched_candidate_count INTEGER NOT NULL CHECK(matched_candidate_count >= 0),
                    selected_records_json TEXT NOT NULL,
                    candidate_groups_json TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    suggestion TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, settlement_record_id)
                );

                CREATE INDEX IF NOT EXISTS idx_refund_reconciliation_runs_task
                    ON refund_reconciliation_runs(task_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_refund_reconciliation_results_filter
                    ON refund_reconciliation_results(run_id, status, settlement_row_number);
                CREATE INDEX IF NOT EXISTS idx_refund_reconciliation_results_identifier
                    ON refund_reconciliation_results(task_id, primary_identifier, after_sale_id);
                """
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (8, utc_now()),
            )

        version_nine = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 9"
        ).fetchone()
        if not version_nine:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS supplementary_reconciliation_runs (
                    id TEXT PRIMARY KEY,
                    import_id TEXT NOT NULL REFERENCES data_imports(id) ON DELETE CASCADE,
                    file_version_id TEXT NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    rule_version_id TEXT NOT NULL REFERENCES rule_versions(id),
                    result_type TEXT NOT NULL CHECK(result_type = 'supplementary'),
                    status TEXT NOT NULL CHECK(status IN ('passed', 'needs_attention')),
                    settlement_wait_days INTEGER NOT NULL CHECK(settlement_wait_days > 0),
                    attention_count INTEGER NOT NULL CHECK(attention_count >= 0),
                    summary_json TEXT NOT NULL,
                    source_snapshot_json TEXT NOT NULL,
                    is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0, 1)),
                    superseded_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS supplementary_reconciliation_results (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL
                        REFERENCES supplementary_reconciliation_runs(id) ON DELETE CASCADE,
                    import_id TEXT NOT NULL REFERENCES data_imports(id) ON DELETE CASCADE,
                    file_version_id TEXT NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    result_type TEXT NOT NULL CHECK(result_type IN (
                        'cross_month', 'after_sale', 'cost', 'other_fund'
                    )),
                    status TEXT NOT NULL,
                    primary_identifier TEXT,
                    source_record_id INTEGER NOT NULL
                        REFERENCES source_records(id) ON DELETE CASCADE,
                    source_row_number INTEGER NOT NULL CHECK(source_row_number > 0),
                    linked_source_record_id INTEGER
                        REFERENCES source_records(id) ON DELETE SET NULL,
                    linked_row_number INTEGER,
                    amount_cents INTEGER,
                    calculated_amount_cents INTEGER,
                    group_key TEXT,
                    metadata_json TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    suggestion TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, result_type, source_record_id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_supplementary_runs_current
                    ON supplementary_reconciliation_runs(import_id)
                    WHERE is_current = 1;
                CREATE INDEX IF NOT EXISTS idx_supplementary_runs_task
                    ON supplementary_reconciliation_runs(task_id, is_current, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_supplementary_results_filter
                    ON supplementary_reconciliation_results(
                        run_id, result_type, status, source_row_number
                    );
                CREATE INDEX IF NOT EXISTS idx_supplementary_results_identifier
                    ON supplementary_reconciliation_results(
                        task_id, result_type, primary_identifier
                    );
                """
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (9, utc_now()),
            )

        version_ten = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 10"
        ).fetchone()
        if not version_ten:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS manual_resolution_events (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    file_version_id TEXT NOT NULL
                        REFERENCES file_versions(id) ON DELETE CASCADE,
                    result_type TEXT NOT NULL CHECK(result_type IN (
                        'ordinary_settlement', 'refund_settlement',
                        'cross_month', 'after_sale', 'cost', 'other_fund'
                    )),
                    result_id TEXT NOT NULL,
                    system_status TEXT NOT NULL,
                    resolution_state TEXT NOT NULL CHECK(resolution_state IN (
                        'resolved', 'carried_forward'
                    )),
                    action_type TEXT NOT NULL CHECK(action_type IN (
                        'confirm', 'select_candidate', 'adjust_amount', 'carry_forward'
                    )),
                    selected_candidate_key TEXT,
                    adjusted_amount_cents INTEGER,
                    follow_up_date TEXT,
                    reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500),
                    previous_event_id TEXT
                        REFERENCES manual_resolution_events(id) ON DELETE SET NULL,
                    is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0, 1)),
                    created_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_manual_resolution_current
                    ON manual_resolution_events(
                        task_id, file_version_id, result_type, result_id
                    ) WHERE is_current = 1;
                CREATE INDEX IF NOT EXISTS idx_manual_resolution_task
                    ON manual_resolution_events(
                        task_id, file_version_id, is_current, created_at DESC
                    );

                CREATE TABLE IF NOT EXISTS period_lifecycle_events (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    action TEXT NOT NULL CHECK(action IN ('completed', 'reopened')),
                    reason TEXT,
                    summary_json TEXT NOT NULL,
                    rule_version_id TEXT NOT NULL REFERENCES rule_versions(id),
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_period_lifecycle_task
                    ON period_lifecycle_events(task_id, created_at DESC);
                """
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (10, utc_now()),
            )

        version_eleven = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 11"
        ).fetchone()
        if not version_eleven:
            connection.executescript(
                """
                ALTER TABLE refund_reconciliation_results
                    ADD COLUMN component_status TEXT;
                ALTER TABLE refund_reconciliation_results
                    ADD COLUMN component_json TEXT;
                """
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (11, utc_now()),
            )

        version_twelve = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 12"
        ).fetchone()
        if not version_twelve:
            now = utc_now()
            current_rule = connection.execute(
                """
                SELECT tolerance_cents, refund_auto_group_seconds,
                       refund_candidate_seconds, settlement_wait_days
                FROM rule_versions
                WHERE status = 'current'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
            parameters = tuple(current_rule) if current_rule else (1, 300, 86400, 7)
            connection.execute("UPDATE rule_versions SET status = 'inactive' WHERE status = 'current'")
            connection.execute(
                """
                INSERT OR IGNORE INTO rule_versions (
                    id, version_label, tolerance_cents, refund_auto_group_seconds,
                    refund_candidate_seconds, settlement_wait_days, status, created_at
                ) VALUES ('rule-v1-1', 'V1.1', ?, ?, ?, ?, 'current', ?)
                """,
                (*parameters, now),
            )
            connection.execute(
                "UPDATE rule_versions SET status = 'current' WHERE id = 'rule-v1-1'"
            )
            connection.execute(
                """
                UPDATE tasks
                SET rule_version_id = 'rule-v1-1', updated_at = ?
                WHERE status != 'completed'
                """,
                (now,),
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (12, now),
            )

        version_thirteen = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 13"
        ).fetchone()
        if not version_thirteen:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS platform_balance_files (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    original_name TEXT NOT NULL,
                    stored_name TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                    replacement_reason TEXT,
                    mapping_version TEXT NOT NULL,
                    is_simulated_mapping INTEGER NOT NULL DEFAULT 1
                        CHECK(is_simulated_mapping IN (0, 1)),
                    inspection_status TEXT NOT NULL
                        CHECK(inspection_status IN ('passed', 'failed')),
                    inspection_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(task_id, content_sha256)
                );

                CREATE TABLE IF NOT EXISTS platform_balance_runs (
                    id TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL UNIQUE
                        REFERENCES platform_balance_files(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    rule_version_id TEXT NOT NULL REFERENCES rule_versions(id),
                    mapping_version TEXT NOT NULL,
                    enforcement_mode TEXT NOT NULL
                        CHECK(enforcement_mode IN ('informational', 'blocking')),
                    status TEXT NOT NULL
                        CHECK(status IN ('passed', 'needs_attention', 'failed')),
                    tolerance_cents INTEGER NOT NULL CHECK(tolerance_cents >= 0),
                    total_result_count INTEGER NOT NULL CHECK(total_result_count >= 0),
                    matched_count INTEGER NOT NULL CHECK(matched_count >= 0),
                    attention_count INTEGER NOT NULL CHECK(attention_count >= 0),
                    summary_json TEXT NOT NULL,
                    is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0, 1)),
                    superseded_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS platform_balance_source_rows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id TEXT NOT NULL
                        REFERENCES platform_balance_files(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    sheet_name TEXT NOT NULL,
                    row_number INTEGER NOT NULL CHECK(row_number > 0),
                    record_type TEXT NOT NULL,
                    raw_values_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(file_id, sheet_name, row_number)
                );

                CREATE TABLE IF NOT EXISTS platform_balance_results (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL
                        REFERENCES platform_balance_runs(id) ON DELETE CASCADE,
                    file_id TEXT NOT NULL
                        REFERENCES platform_balance_files(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    level TEXT NOT NULL CHECK(level IN ('day', 'month', 'source')),
                    status TEXT NOT NULL,
                    batch_key TEXT,
                    account TEXT,
                    period_key TEXT,
                    source_sheet TEXT NOT NULL,
                    source_row_number INTEGER NOT NULL CHECK(source_row_number > 0),
                    summary_count INTEGER,
                    detail_count INTEGER,
                    summary_income_cents INTEGER,
                    detail_income_cents INTEGER,
                    summary_expense_cents INTEGER,
                    detail_expense_cents INTEGER,
                    opening_balance_cents INTEGER,
                    closing_balance_cents INTEGER,
                    calculated_closing_balance_cents INTEGER,
                    difference_cents INTEGER,
                    metadata_json TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    suggestion TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_platform_balance_runs_current
                    ON platform_balance_runs(task_id) WHERE is_current = 1;
                CREATE INDEX IF NOT EXISTS idx_platform_balance_files_task
                    ON platform_balance_files(task_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_platform_balance_results_filter
                    ON platform_balance_results(run_id, status, level, source_row_number);
                CREATE INDEX IF NOT EXISTS idx_platform_balance_source_rows
                    ON platform_balance_source_rows(file_id, sheet_name, row_number);
                """
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (13, utc_now()),
            )

        version_fourteen = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 14"
        ).fetchone()
        if not version_fourteen:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS pending_settlement_files (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    original_name TEXT NOT NULL,
                    stored_name TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                    replacement_reason TEXT,
                    mapping_version TEXT NOT NULL,
                    is_simulated_mapping INTEGER NOT NULL DEFAULT 1
                        CHECK(is_simulated_mapping IN (0, 1)),
                    inspection_status TEXT NOT NULL
                        CHECK(inspection_status IN ('passed', 'failed')),
                    inspection_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(task_id, content_sha256)
                );

                CREATE TABLE IF NOT EXISTS pending_settlement_runs (
                    id TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL UNIQUE
                        REFERENCES pending_settlement_files(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    rule_version_id TEXT NOT NULL REFERENCES rule_versions(id),
                    mapping_version TEXT NOT NULL,
                    enforcement_mode TEXT NOT NULL
                        CHECK(enforcement_mode IN ('informational', 'blocking')),
                    status TEXT NOT NULL
                        CHECK(status IN ('passed', 'needs_attention', 'failed')),
                    as_of TEXT NOT NULL,
                    wait_days INTEGER NOT NULL CHECK(wait_days > 0),
                    total_result_count INTEGER NOT NULL CHECK(total_result_count >= 0),
                    attention_count INTEGER NOT NULL CHECK(attention_count >= 0),
                    waiting_count INTEGER NOT NULL CHECK(waiting_count >= 0),
                    overdue_count INTEGER NOT NULL CHECK(overdue_count >= 0),
                    excluded_count INTEGER NOT NULL CHECK(excluded_count >= 0),
                    pending_amount_cents INTEGER NOT NULL,
                    summary_json TEXT NOT NULL,
                    is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0, 1)),
                    superseded_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pending_settlement_source_rows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id TEXT NOT NULL
                        REFERENCES pending_settlement_files(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    sheet_name TEXT NOT NULL,
                    row_number INTEGER NOT NULL CHECK(row_number > 0),
                    record_type TEXT NOT NULL,
                    raw_values_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(file_id, sheet_name, row_number)
                );

                CREATE TABLE IF NOT EXISTS pending_settlement_results (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL
                        REFERENCES pending_settlement_runs(id) ON DELETE CASCADE,
                    file_id TEXT NOT NULL
                        REFERENCES pending_settlement_files(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    scene_code TEXT NOT NULL,
                    order_id TEXT,
                    suborder_id TEXT,
                    product_id TEXT,
                    payment_cents INTEGER,
                    order_status TEXT,
                    settlement_status TEXT,
                    settlement_cycle TEXT,
                    expected_settlement_at TEXT,
                    expected_settlement_cents INTEGER,
                    completed_at TEXT,
                    after_sales_status TEXT,
                    restriction_status TEXT,
                    entered_settlement TEXT,
                    recheck_at TEXT,
                    completion_condition TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_sheet TEXT NOT NULL,
                    source_row_number INTEGER NOT NULL CHECK(source_row_number > 0),
                    aux_source_sheet TEXT,
                    aux_source_row_number INTEGER,
                    metadata_json TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    suggestion TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_settlement_runs_current
                    ON pending_settlement_runs(task_id) WHERE is_current = 1;
                CREATE INDEX IF NOT EXISTS idx_pending_settlement_files_task
                    ON pending_settlement_files(task_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_pending_settlement_results_filter
                    ON pending_settlement_results(run_id, status, scene_code);
                CREATE INDEX IF NOT EXISTS idx_pending_settlement_source_rows
                    ON pending_settlement_source_rows(file_id, sheet_name, row_number);
                """
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (14, utc_now()),
            )

        version_fifteen = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 15"
        ).fetchone()
        if not version_fifteen:
            now = utc_now()
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS bill_template_versions (
                    id TEXT PRIMARY KEY,
                    platform_code TEXT NOT NULL,
                    template_code TEXT NOT NULL,
                    version_label TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('draft', 'current', 'inactive')),
                    notes TEXT,
                    last_tested_at TEXT,
                    last_test_status TEXT CHECK(last_test_status IN ('passed', 'failed')),
                    last_test_file_name TEXT,
                    last_test_summary_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    activated_at TEXT,
                    UNIQUE(platform_code, template_code, version_label)
                );

                CREATE TABLE IF NOT EXISTS bill_template_sheets (
                    id TEXT PRIMARY KEY,
                    template_version_id TEXT NOT NULL
                        REFERENCES bill_template_versions(id) ON DELETE CASCADE,
                    standard_sheet_code TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    source_sheet_name TEXT NOT NULL,
                    source_sheet_aliases_json TEXT NOT NULL,
                    header_row INTEGER NOT NULL CHECK(header_row > 0),
                    data_start_row INTEGER NOT NULL CHECK(data_start_row > 0),
                    baseline_rows INTEGER,
                    baseline_columns INTEGER,
                    required INTEGER NOT NULL DEFAULT 1 CHECK(required IN (0, 1)),
                    sort_order INTEGER NOT NULL,
                    UNIQUE(template_version_id, standard_sheet_code)
                );

                CREATE TABLE IF NOT EXISTS bill_template_fields (
                    id TEXT PRIMARY KEY,
                    sheet_id TEXT NOT NULL REFERENCES bill_template_sheets(id) ON DELETE CASCADE,
                    standard_field_code TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    source_header TEXT NOT NULL,
                    source_aliases_json TEXT NOT NULL,
                    data_type TEXT NOT NULL DEFAULT 'text'
                        CHECK(data_type IN ('text', 'number', 'money', 'date', 'datetime')),
                    required INTEGER NOT NULL DEFAULT 0 CHECK(required IN (0, 1)),
                    sort_order INTEGER NOT NULL,
                    UNIQUE(sheet_id, standard_field_code)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_bill_template_current
                    ON bill_template_versions(platform_code, template_code)
                    WHERE status = 'current';
                CREATE INDEX IF NOT EXISTS idx_bill_template_sheets_version
                    ON bill_template_sheets(template_version_id, sort_order);
                CREATE INDEX IF NOT EXISTS idx_bill_template_fields_sheet
                    ON bill_template_fields(sheet_id, sort_order);

                ALTER TABLE file_versions ADD COLUMN template_version_id TEXT
                    REFERENCES bill_template_versions(id);
                CREATE INDEX IF NOT EXISTS idx_file_versions_template
                    ON file_versions(template_version_id, created_at DESC);
                """
            )
            connection.execute(
                """
                INSERT INTO bill_template_versions (
                    id, platform_code, template_code, version_label, name, status,
                    notes, last_tested_at, last_test_status, last_test_file_name,
                    last_test_summary_json, created_at, updated_at, activated_at
                ) VALUES (?, 'DOUYIN', ?, 'V1.0', '抖店五表默认模板', 'current', ?, ?,
                          'passed', '抖店练习数据.xlsx', ?, ?, ?, ?)
                """,
                (
                    DEFAULT_TEMPLATE_ID,
                    DEFAULT_TEMPLATE_CODE,
                    "从当前已验证的五张底表结构生成；发布版本不直接修改。",
                    now,
                    json.dumps({"source": "existing_verified_contract", "sheetCount": 5}, ensure_ascii=False),
                    now,
                    now,
                    now,
                ),
            )
            for sheet_order, definition in enumerate(DEFAULT_TEMPLATE_SHEETS, 1):
                sheet_id = "template-sheet-{}".format(uuid.uuid4().hex)
                connection.execute(
                    """
                    INSERT INTO bill_template_sheets (
                        id, template_version_id, standard_sheet_code, display_name,
                        source_sheet_name, source_sheet_aliases_json, header_row,
                        data_start_row, baseline_rows, baseline_columns, required, sort_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        sheet_id,
                        DEFAULT_TEMPLATE_ID,
                        definition["code"],
                        definition["name"],
                        definition["source_name"],
                        json.dumps(list(definition.get("aliases") or ()), ensure_ascii=False),
                        definition["header_row"],
                        definition["data_start_row"],
                        definition.get("baseline_rows"),
                        definition.get("baseline_columns"),
                        sheet_order,
                    ),
                )
                required_headers = set(definition["required_headers"])
                configured_aliases = definition.get("field_aliases") or {}
                for field_order, header in enumerate(definition["headers"], 1):
                    connection.execute(
                        """
                        INSERT INTO bill_template_fields (
                            id, sheet_id, standard_field_code, display_name,
                            source_header, source_aliases_json, data_type, required, sort_order
                        ) VALUES (?, ?, ?, ?, ?, ?, 'text', ?, ?)
                        """,
                        (
                            "template-field-{}".format(uuid.uuid4().hex),
                            sheet_id,
                            header,
                            header,
                            header,
                            json.dumps(list(configured_aliases.get(header) or ()), ensure_ascii=False),
                            1 if header in required_headers else 0,
                            field_order,
                        ),
                    )
            # Version 15 introduces template provenance. Every file imported before
            # this migration used the only then-supported five-sheet contract, so
            # backfill that version instead of leaving historical files unauditable.
            connection.execute(
                """
                UPDATE file_versions
                SET template_version_id = ?
                WHERE template_version_id IS NULL
                """,
                (DEFAULT_TEMPLATE_ID,),
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (15, now),
            )

        version_sixteen = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 16"
        ).fetchone()
        if not version_sixteen:
            now = utc_now()
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS rule_version_drafts (
                    id TEXT PRIMARY KEY,
                    source_rule_version_id TEXT NOT NULL
                        REFERENCES rule_versions(id),
                    version_label TEXT NOT NULL UNIQUE,
                    tolerance_cents INTEGER NOT NULL
                        CHECK(tolerance_cents BETWEEN 0 AND 100),
                    refund_auto_group_seconds INTEGER NOT NULL
                        CHECK(refund_auto_group_seconds BETWEEN 60 AND 3600),
                    refund_candidate_seconds INTEGER NOT NULL
                        CHECK(refund_candidate_seconds BETWEEN 61 AND 259200),
                    settlement_wait_days INTEGER NOT NULL
                        CHECK(settlement_wait_days BETWEEN 1 AND 90),
                    notes TEXT,
                    last_tested_at TEXT,
                    last_test_status TEXT
                        CHECK(last_test_status IN ('passed', 'failed')),
                    last_test_summary_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK(refund_candidate_seconds > refund_auto_group_seconds)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_rule_versions_current
                    ON rule_versions(status) WHERE status = 'current';

                ALTER TABLE rule_versions ADD COLUMN notes TEXT;
                ALTER TABLE rule_versions ADD COLUMN activated_at TEXT;
                ALTER TABLE rule_versions ADD COLUMN fixed_case_summary_json TEXT;
                """
            )
            connection.execute(
                """
                UPDATE rule_versions
                SET activated_at = created_at
                WHERE activated_at IS NULL
                """
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (16, now),
            )

        version_seventeen = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 17"
        ).fetchone()
        if not version_seventeen:
            now = utc_now()
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS business_entities (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE CHECK(length(name) BETWEEN 1 AND 100),
                    status TEXT NOT NULL CHECK(status IN ('active', 'inactive')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS platform_stores (
                    id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL REFERENCES business_entities(id),
                    platform_code TEXT NOT NULL,
                    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 100),
                    status TEXT NOT NULL CHECK(status IN ('active', 'inactive')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(entity_id, platform_code, name)
                );

                ALTER TABLE tasks ADD COLUMN entity_id TEXT REFERENCES business_entities(id);
                ALTER TABLE tasks ADD COLUMN store_id TEXT REFERENCES platform_stores(id);

                CREATE TABLE IF NOT EXISTS platform_value_mappings (
                    id TEXT PRIMARY KEY,
                    mapping_type TEXT NOT NULL
                        CHECK(mapping_type IN ('after_sale_status', 'fund_scene')),
                    source_value TEXT NOT NULL CHECK(length(source_value) BETWEEN 1 AND 200),
                    standard_code TEXT NOT NULL,
                    standard_name TEXT NOT NULL,
                    canonical_value TEXT NOT NULL,
                    version_number INTEGER NOT NULL CHECK(version_number > 0),
                    version_label TEXT NOT NULL,
                    effective_from TEXT NOT NULL CHECK(length(effective_from) = 10),
                    is_current INTEGER NOT NULL CHECK(is_current IN (0, 1)),
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(mapping_type, source_value, version_number)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_platform_value_mapping_current
                    ON platform_value_mappings(mapping_type, source_value)
                    WHERE is_current = 1;
                CREATE INDEX IF NOT EXISTS idx_platform_value_mapping_effective
                    ON platform_value_mappings(mapping_type, source_value, effective_from DESC);

                CREATE TABLE IF NOT EXISTS unmapped_platform_values (
                    id TEXT PRIMARY KEY,
                    mapping_type TEXT NOT NULL
                        CHECK(mapping_type IN ('after_sale_status', 'fund_scene')),
                    source_value TEXT NOT NULL CHECK(length(source_value) BETWEEN 1 AND 200),
                    first_task_id TEXT REFERENCES tasks(id),
                    latest_task_id TEXT REFERENCES tasks(id),
                    occurrence_count INTEGER NOT NULL CHECK(occurrence_count > 0),
                    status TEXT NOT NULL CHECK(status IN ('pending', 'mapped')),
                    resolved_mapping_id TEXT REFERENCES platform_value_mappings(id),
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    resolved_at TEXT,
                    UNIQUE(mapping_type, source_value)
                );

                ALTER TABLE source_records ADD COLUMN mapped_values_json TEXT;
                ALTER TABLE source_records ADD COLUMN mapping_snapshot_json TEXT;

                CREATE INDEX IF NOT EXISTS idx_platform_stores_entity
                    ON platform_stores(entity_id, status, name);
                CREATE INDEX IF NOT EXISTS idx_tasks_master_store
                    ON tasks(store_id, period DESC);
                CREATE INDEX IF NOT EXISTS idx_unmapped_platform_values_status
                    ON unmapped_platform_values(status, mapping_type, last_seen_at DESC);
                """
            )

            # Existing task names become maintained master data without changing the
            # task's historical text fields. Sample tasks stay independent.
            task_pairs = connection.execute(
                """
                SELECT DISTINCT entity_name, store_name
                FROM tasks WHERE is_sample = 0
                ORDER BY entity_name, store_name
                """
            ).fetchall()
            entity_ids = {}
            for row in task_pairs:
                entity_name = row["entity_name"]
                entity_id = entity_ids.get(entity_name)
                if entity_id is None:
                    entity_id = "entity-{}".format(uuid.uuid4().hex)
                    entity_ids[entity_name] = entity_id
                    connection.execute(
                        """
                        INSERT INTO business_entities (id, name, status, created_at, updated_at)
                        VALUES (?, ?, 'active', ?, ?)
                        """,
                        (entity_id, entity_name, now, now),
                    )
                store_id = "store-{}".format(uuid.uuid4().hex)
                connection.execute(
                    """
                    INSERT INTO platform_stores (
                        id, entity_id, platform_code, name, status, created_at, updated_at
                    ) VALUES (?, ?, 'DOUYIN', ?, 'active', ?, ?)
                    """,
                    (store_id, entity_id, row["store_name"], now, now),
                )
                connection.execute(
                    """
                    UPDATE tasks SET entity_id = ?, store_id = ?
                    WHERE is_sample = 0 AND entity_name = ? AND store_name = ?
                    """,
                    (entity_id, store_id, entity_name, row["store_name"]),
                )

            standard_lookup = {
                (mapping_type, item["code"]): item
                for mapping_type, definition in VALUE_MAPPING_TYPES.items()
                for item in definition["standards"]
            }
            for mapping_type, source_value, standard_code in DEFAULT_PLATFORM_VALUE_MAPPINGS:
                standard = standard_lookup[(mapping_type, standard_code)]
                connection.execute(
                    """
                    INSERT INTO platform_value_mappings (
                        id, mapping_type, source_value, standard_code, standard_name,
                        canonical_value, version_number, version_label, effective_from,
                        is_current, notes, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, 'V1', '2000-01-01', 1, ?, ?)
                    """,
                    (
                        "mapping-{}".format(uuid.uuid4().hex), mapping_type,
                        source_value, standard_code, standard["name"],
                        standard["canonicalValue"], "系统已验证基线映射", now,
                    ),
                )

            connection.execute(
                """
                UPDATE source_records
                SET mapped_values_json = raw_values_json
                WHERE mapped_values_json IS NULL
                """
            )
            known_sources = {
                (row["mapping_type"], row["source_value"])
                for row in connection.execute(
                    "SELECT mapping_type, source_value FROM platform_value_mappings"
                ).fetchall()
            }
            mapping_type_by_record = {
                definition["recordType"]: (mapping_type, definition["sourceField"])
                for mapping_type, definition in VALUE_MAPPING_TYPES.items()
            }
            unknown_counts = {}
            source_rows = connection.execute(
                """
                SELECT task_id, record_type, raw_values_json
                FROM source_records
                WHERE record_type IN ('after_sale', 'fund')
                """
            ).fetchall()
            for source_row in source_rows:
                type_info = mapping_type_by_record.get(source_row["record_type"])
                if type_info is None:
                    continue
                mapping_type, field_name = type_info
                values = json.loads(source_row["raw_values_json"] or "{}")
                source_value = " ".join(str(values.get(field_name) or "").strip().split())
                if not source_value or (mapping_type, source_value) in known_sources:
                    continue
                key = (mapping_type, source_value)
                item = unknown_counts.setdefault(
                    key, {"count": 0, "first_task_id": source_row["task_id"], "latest_task_id": source_row["task_id"]}
                )
                item["count"] += 1
                item["latest_task_id"] = source_row["task_id"]
            for (mapping_type, source_value), item in unknown_counts.items():
                connection.execute(
                    """
                    INSERT INTO unmapped_platform_values (
                        id, mapping_type, source_value, first_task_id, latest_task_id,
                        occurrence_count, status, first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        "unmapped-{}".format(uuid.uuid4().hex), mapping_type,
                        source_value, item["first_task_id"], item["latest_task_id"],
                        item["count"], now, now,
                    ),
                )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (17, now),
            )

        version_eighteen = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 18"
        ).fetchone()
        if not version_eighteen:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS operating_evidence_files (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    evidence_type TEXT NOT NULL CHECK(evidence_type IN (
                        'erp_cost', 'fulfillment_expense', 'operating_expense'
                    )),
                    original_name TEXT NOT NULL,
                    stored_name TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL CHECK(size_bytes > 0),
                    replacement_reason TEXT,
                    processing_status TEXT NOT NULL
                        CHECK(processing_status IN ('received_pending_mapping')),
                    created_at TEXT NOT NULL,
                    UNIQUE(task_id, evidence_type, content_sha256)
                );

                CREATE INDEX IF NOT EXISTS idx_operating_evidence_task_type
                    ON operating_evidence_files(task_id, evidence_type, created_at DESC);
                """
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (18, utc_now()),
            )

        version_nineteen = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 19"
        ).fetchone()
        if not version_nineteen:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS operating_evidence_runs (
                    id TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL UNIQUE
                        REFERENCES operating_evidence_files(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    evidence_type TEXT NOT NULL CHECK(evidence_type IN (
                        'erp_cost', 'fulfillment_expense', 'operating_expense'
                    )),
                    mapping_version TEXT NOT NULL,
                    data_mode TEXT NOT NULL CHECK(data_mode IN (
                        'simulated_trial', 'formal'
                    )),
                    status TEXT NOT NULL CHECK(status IN (
                        'passed', 'needs_attention', 'failed'
                    )),
                    total_row_count INTEGER NOT NULL CHECK(total_row_count >= 0),
                    matched_row_count INTEGER NOT NULL CHECK(matched_row_count >= 0),
                    attention_count INTEGER NOT NULL CHECK(attention_count >= 0),
                    total_amount_cents INTEGER,
                    summary_json TEXT NOT NULL,
                    is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0, 1)),
                    superseded_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_operating_evidence_current_run
                    ON operating_evidence_runs(task_id, evidence_type)
                    WHERE is_current = 1;

                CREATE TABLE IF NOT EXISTS operating_evidence_rows (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL
                        REFERENCES operating_evidence_runs(id) ON DELETE CASCADE,
                    file_id TEXT NOT NULL
                        REFERENCES operating_evidence_files(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    evidence_type TEXT NOT NULL,
                    sheet_name TEXT NOT NULL,
                    row_number INTEGER NOT NULL CHECK(row_number > 0),
                    primary_identifier TEXT,
                    secondary_identifier TEXT,
                    status TEXT NOT NULL CHECK(status IN ('matched', 'needs_attention')),
                    amount_cents INTEGER,
                    details_json TEXT NOT NULL,
                    raw_values_json TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, row_number)
                );

                CREATE INDEX IF NOT EXISTS idx_operating_evidence_rows_run_status
                    ON operating_evidence_rows(run_id, status, row_number);
                """
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (19, utc_now()),
            )


def row_to_dict(row):
    return dict(row) if row is not None else None


def append_operation(connection, task_id, action, reason=None, details=None):
    connection.execute(
        """
        INSERT INTO operation_logs(task_id, action, reason, details_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (task_id, action, reason, json.dumps(details or {}, ensure_ascii=False), utc_now()),
    )
