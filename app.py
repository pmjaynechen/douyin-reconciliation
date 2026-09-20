#!/usr/bin/env python3
import argparse
import json

from recon_app import __version__
from recon_app.api import ApiApplication
from recon_app.backup_restore import (
    BackupError,
    assert_application_stopped,
    create_backup,
    restore_backup,
    verify_backup,
)
from recon_app.config import AppConfig
from recon_app.database import initialize_database
from recon_app.fixed_cases import run_fixed_cases
from recon_app.server import run_server
from recon_app.services import ReconciliationService


def build_application(data_dir=None):
    config = AppConfig(data_dir=data_dir)
    config.ensure_directories()
    initialize_database(config.database_path)
    service = ReconciliationService(
        config.database_path, config.upload_dir, config.sample_workbook_path
    )
    service.backfill_pending_imports()
    service.backfill_pending_amount_checks()
    service.backfill_pending_reconciliations()
    service.backfill_pending_refund_reconciliations()
    service.backfill_pending_refund_component_checks()
    service.backfill_pending_supplementary_reconciliations()
    service.backfill_current_control_reconciliations()
    return config, ApiApplication(service), service


def main():
    parser = argparse.ArgumentParser(description="抖店对账本机应用")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--data-dir", default=None)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--self-check", action="store_true")
    actions.add_argument("--fixed-cases", action="store_true")
    actions.add_argument("--backup", action="store_true")
    actions.add_argument("--verify-backup", metavar="ZIP_PATH")
    actions.add_argument("--restore", metavar="ZIP_PATH")
    parser.add_argument("--backup-dir", default=None)
    args = parser.parse_args()

    if args.backup_dir and not args.backup:
        parser.error("--backup-dir只能与--backup一起使用")

    if args.fixed_cases:
        result = run_fixed_cases(AppConfig(data_dir=args.data_dir).base_dir)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "passed" else 1

    config = AppConfig(data_dir=args.data_dir)
    try:
        if args.backup:
            assert_application_stopped(config.data_dir, args.host, args.port)
            result = create_backup(config.data_dir, args.backup_dir, __version__)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.verify_backup:
            result = verify_backup(args.verify_backup)
            result.pop("manifest", None)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.restore:
            assert_application_stopped(config.data_dir, args.host, args.port)
            result = restore_backup(args.restore, config.data_dir)
            print(json.dumps(result, ensure_ascii=False))
            return 0
    except BackupError as exc:
        parser.exit(1, "{}\n".format(exc))

    config, api, service = build_application(args.data_dir)
    if args.self_check:
        print(json.dumps(service.health(), ensure_ascii=False))
        return 0
    run_server(args.host, args.port, api, config.web_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
