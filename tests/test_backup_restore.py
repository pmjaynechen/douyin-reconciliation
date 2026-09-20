import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from recon_app.backup_restore import (
    BackupError,
    create_backup,
    restore_backup,
    verify_backup,
)
from recon_app.database import initialize_database
from recon_app.services import ReconciliationService
from xlsx_fixture import build_workbook_bytes


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data_dir = self.root / "var"
        self.backup_dir = self.root / "backups"
        self.database_path = self.data_dir / "reconciliation.db"
        self.upload_dir = self.data_dir / "uploads"
        initialize_database(self.database_path)
        self.service = ReconciliationService(self.database_path, self.upload_dir)
        self.task = self.service.create_task(
            {"entityName": "备份主体", "storeName": "备份店铺", "period": "2023-12"}
        )
        self.uploaded = self.service.upload_workbook(
            self.task["id"], "备份源.xlsx", build_workbook_bytes()
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_backup_verify_restore_and_preserve_previous_data(self):
        created = create_backup(self.data_dir, self.backup_dir, "test-version")
        backup_path = Path(created["backupPath"])
        self.assertTrue(backup_path.is_file())
        self.assertEqual(created["schemaVersion"], 19)

        verified = verify_backup(backup_path)
        self.assertEqual(verified["status"], "valid")
        self.assertEqual(verified["appVersion"], "test-version")
        self.assertGreaterEqual(verified["fileCount"], 2)

        extra = self.service.create_task(
            {"entityName": "恢复前新增", "storeName": "恢复前店铺", "period": "2024-01"}
        )
        self.assertEqual(len(self.service.list_tasks()), 2)

        restored = restore_backup(backup_path, self.data_dir)
        self.assertEqual(restored["status"], "restored")
        self.assertEqual(restored["schemaVersion"], 19)
        recovery_path = Path(restored["recoveryPath"])
        self.assertTrue(recovery_path.is_dir())

        restored_service = ReconciliationService(
            self.data_dir / "reconciliation.db", self.data_dir / "uploads"
        )
        tasks = restored_service.list_tasks()
        self.assertEqual([item["id"] for item in tasks], [self.task["id"]])
        detail = restored_service.get_task(self.task["id"])
        self.assertEqual(detail["files"][0]["id"], self.uploaded["file"]["id"])
        restored_upload = (
            self.data_dir / "uploads" / self.task["id"]
            / "{}.xlsx".format(self.uploaded["file"]["id"])
        )
        self.assertTrue(restored_upload.is_file())

        recovery_service = ReconciliationService(
            recovery_path / "reconciliation.db", recovery_path / "uploads"
        )
        self.assertIn(extra["id"], {item["id"] for item in recovery_service.list_tasks()})

    def test_changed_file_hash_is_rejected(self):
        created = create_backup(self.data_dir, self.backup_dir, "test-version")
        source = Path(created["backupPath"])
        changed = self.root / "changed-hash.zip"
        with zipfile.ZipFile(str(source), "r") as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(contents["manifest.json"].decode("utf-8"))
        manifest["files"][0]["sha256"] = "0" * 64
        contents["manifest.json"] = json.dumps(manifest).encode("utf-8")
        with zipfile.ZipFile(str(changed), "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in contents.items():
                archive.writestr(name, content)
        with self.assertRaises(BackupError):
            verify_backup(changed)

    def test_unsafe_archive_path_is_rejected(self):
        unsafe = self.root / "unsafe.zip"
        with zipfile.ZipFile(str(unsafe), "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("../escape.txt", "不能写出备份目录")
            archive.writestr("manifest.json", "{}")
        with self.assertRaises(BackupError):
            verify_backup(unsafe)


if __name__ == "__main__":
    unittest.main()
