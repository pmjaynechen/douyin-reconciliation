import hashlib
import json
import os
import shutil
import socket
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .database import SCHEMA_VERSION


BACKUP_FORMAT_VERSION = 1
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_BACKUP_CONTENT_BYTES = 5 * 1024 * 1024 * 1024


class BackupError(Exception):
    pass


def default_backup_dir():
    return Path.home() / "Documents" / "抖店对账备份"


def assert_application_stopped(data_dir, host="127.0.0.1", port=8766):
    data_dir = _safe_data_dir(data_dir)
    pid_path = data_dir / "app.pid"
    if pid_path.is_file():
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = None
        if pid and _process_is_running(pid):
            raise BackupError("抖店对账仍在运行，请先在应用终端按Control+C停止。")

    try:
        connection = socket.create_connection((host, int(port)), timeout=0.3)
    except (OSError, ValueError):
        return
    else:
        connection.close()
        raise BackupError(
            "{}:{}仍有服务在运行，请先停止应用再备份或恢复。".format(host, port)
        )


def create_backup(data_dir, destination_dir=None, app_version=None):
    data_dir = _safe_data_dir(data_dir)
    database_path = data_dir / "reconciliation.db"
    upload_dir = data_dir / "uploads"
    if not database_path.is_file():
        raise BackupError("没有找到对账数据库，当前没有可备份的数据。")

    destination_dir = Path(destination_dir or default_backup_dir()).expanduser().resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).replace(microsecond=0)
    file_name = "douyin-reconciliation-backup-{}-{}.zip".format(
        timestamp.strftime("%Y%m%d-%H%M%SZ"), uuid.uuid4().hex[:6]
    )
    final_path = destination_dir / file_name
    temporary_archive = destination_dir / ".{}.tmp".format(uuid.uuid4().hex)

    try:
        with tempfile.TemporaryDirectory(prefix=".douyin-backup-") as temp_dir:
            stage = Path(temp_dir)
            snapshot_database = stage / "reconciliation.db"
            _snapshot_database(database_path, snapshot_database)
            schema_version = _database_schema_version(snapshot_database)
            if schema_version > SCHEMA_VERSION:
                raise BackupError(
                    "数据库版本{}高于当前程序支持的{}，不能生成不兼容备份。".format(
                        schema_version, SCHEMA_VERSION
                    )
                )

            if upload_dir.exists():
                _copy_uploads(upload_dir, stage / "uploads")
            else:
                (stage / "uploads").mkdir(parents=True, exist_ok=True)

            entries = _manifest_entries(stage)
            manifest = {
                "formatVersion": BACKUP_FORMAT_VERSION,
                "createdAt": timestamp.isoformat().replace("+00:00", "Z"),
                "appVersion": app_version,
                "schemaVersion": schema_version,
                "files": entries,
            }
            (stage / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            with zipfile.ZipFile(
                str(temporary_archive), "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for source in sorted(stage.rglob("*")):
                    if source.is_file():
                        archive.write(str(source), source.relative_to(stage).as_posix())
            os.replace(str(temporary_archive), str(final_path))
        verification = verify_backup(final_path)
    except BackupError:
        _remove_file_if_exists(temporary_archive)
        _remove_file_if_exists(final_path)
        raise
    except (OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
        _remove_file_if_exists(temporary_archive)
        _remove_file_if_exists(final_path)
        raise BackupError("备份失败：{}".format(exc))

    return {
        "status": "created",
        "backupPath": str(final_path),
        "createdAt": manifest["createdAt"],
        "schemaVersion": manifest["schemaVersion"],
        "fileCount": verification["fileCount"],
        "totalBytes": verification["totalBytes"],
    }


def verify_backup(archive_path, max_schema_version=SCHEMA_VERSION):
    archive_path = Path(archive_path).expanduser().resolve()
    if not archive_path.is_file():
        raise BackupError("没有找到备份文件：{}".format(archive_path))
    try:
        with zipfile.ZipFile(str(archive_path), "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise BackupError("备份包中出现重复文件名。")
            for info in infos:
                _validate_archive_name(info.filename)
                if info.is_dir():
                    raise BackupError("备份包不应包含空目录记录。")
            manifest_info = archive.getinfo("manifest.json")
            if manifest_info.file_size > MAX_MANIFEST_BYTES:
                raise BackupError("备份说明文件过大。")
            try:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            except (KeyError, UnicodeDecodeError, ValueError):
                raise BackupError("备份说明文件缺失或无法读取。")
            _validate_manifest(manifest, max_schema_version)

            expected = {item["path"]: item for item in manifest["files"]}
            actual_names = set(names) - {"manifest.json"}
            if set(expected) != actual_names:
                raise BackupError("备份说明与实际文件清单不一致。")
            if "reconciliation.db" not in expected:
                raise BackupError("备份包缺少对账数据库。")

            total_bytes = 0
            for name, expected_entry in expected.items():
                info = archive.getinfo(name)
                total_bytes += info.file_size
                if total_bytes > MAX_BACKUP_CONTENT_BYTES:
                    raise BackupError("备份内容超过允许的最大容量。")
                if info.file_size != expected_entry["sizeBytes"]:
                    raise BackupError("备份文件大小校验失败：{}".format(name))
                digest = _hash_archive_entry(archive, name)
                if digest != expected_entry["sha256"]:
                    raise BackupError("备份文件内容校验失败：{}".format(name))
            damaged = archive.testzip()
            if damaged:
                raise BackupError("备份压缩包损坏：{}".format(damaged))
    except BackupError:
        raise
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise BackupError("备份文件无法打开：{}".format(exc))

    return {
        "status": "valid",
        "backupPath": str(archive_path),
        "createdAt": manifest.get("createdAt"),
        "appVersion": manifest.get("appVersion"),
        "schemaVersion": manifest["schemaVersion"],
        "fileCount": len(expected),
        "totalBytes": total_bytes,
        "manifest": manifest,
    }


def restore_backup(archive_path, data_dir):
    verification = verify_backup(archive_path)
    archive_path = Path(archive_path).expanduser().resolve()
    data_dir = _safe_data_dir(data_dir)
    parent = data_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    stage = parent / ".douyin-restore-{}".format(uuid.uuid4().hex)
    recovery_path = None

    try:
        stage.mkdir()
        with zipfile.ZipFile(str(archive_path), "r") as archive:
            for entry in verification["manifest"]["files"]:
                target = stage / Path(entry["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry["path"], "r") as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        (stage / "uploads").mkdir(parents=True, exist_ok=True)
        restored_database = stage / "reconciliation.db"
        _assert_database_integrity(restored_database)
        restored_schema = _database_schema_version(restored_database)
        if restored_schema != verification["schemaVersion"]:
            raise BackupError("恢复数据库版本与备份说明不一致。")

        if data_dir.exists():
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
            recovery_path = parent / "recovery-before-restore-{}-{}".format(
                timestamp, uuid.uuid4().hex[:6]
            )
            data_dir.replace(recovery_path)
        stage.replace(data_dir)
    except BackupError:
        _rollback_restore(stage, data_dir, recovery_path)
        raise
    except (OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
        _rollback_restore(stage, data_dir, recovery_path)
        raise BackupError("恢复失败，原数据已尽量保留：{}".format(exc))

    return {
        "status": "restored",
        "backupPath": str(archive_path),
        "dataDir": str(data_dir),
        "recoveryPath": str(recovery_path) if recovery_path else None,
        "schemaVersion": restored_schema,
        "fileCount": verification["fileCount"],
    }


def _snapshot_database(source_path, destination_path):
    source = sqlite3.connect(str(source_path), timeout=10)
    destination = sqlite3.connect(str(destination_path))
    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()
    _assert_database_integrity(destination_path)


def _assert_database_integrity(database_path):
    if not Path(database_path).is_file():
        raise BackupError("备份数据库缺失。")
    connection = sqlite3.connect(str(database_path))
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()
        if result is None or result[0] != "ok":
            raise BackupError("数据库完整性检查失败：{}".format(result[0] if result else "无结果"))
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        if table is None:
            raise BackupError("备份数据库不是抖店对账数据库。")
    finally:
        connection.close()


def _database_schema_version(database_path):
    connection = sqlite3.connect(str(database_path))
    try:
        row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    finally:
        connection.close()
    if row is None or row[0] is None:
        raise BackupError("数据库缺少结构版本记录。")
    return int(row[0])


def _copy_uploads(source_dir, destination_dir):
    destination_dir.mkdir(parents=True, exist_ok=True)
    for source in sorted(source_dir.rglob("*")):
        if source.is_symlink():
            raise BackupError("上传目录包含符号链接，已停止备份：{}".format(source.name))
        if source.is_dir():
            continue
        if not source.is_file():
            raise BackupError("上传目录包含不支持的文件类型：{}".format(source.name))
        relative = source.relative_to(source_dir)
        target = destination_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(target))


def _manifest_entries(stage):
    entries = []
    for source in sorted(stage.rglob("*")):
        if not source.is_file() or source.name == "manifest.json":
            continue
        entries.append(
            {
                "path": source.relative_to(stage).as_posix(),
                "sizeBytes": source.stat().st_size,
                "sha256": _hash_file(source),
            }
        )
    return entries


def _validate_manifest(manifest, max_schema_version):
    if not isinstance(manifest, dict):
        raise BackupError("备份说明格式不正确。")
    if manifest.get("formatVersion") != BACKUP_FORMAT_VERSION:
        raise BackupError("备份格式版本不受支持。")
    schema_version = manifest.get("schemaVersion")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise BackupError("备份数据库版本无效。")
    if schema_version > max_schema_version:
        raise BackupError(
            "备份数据库版本{}高于当前程序支持的{}。".format(
                schema_version, max_schema_version
            )
        )
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise BackupError("备份文件清单为空。")
    seen = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise BackupError("备份文件清单格式不正确。")
        path = entry.get("path")
        _validate_archive_name(path)
        if path == "manifest.json" or path in seen:
            raise BackupError("备份文件清单出现重复或保留名称。")
        seen.add(path)
        size = entry.get("sizeBytes")
        digest = entry.get("sha256")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise BackupError("备份文件大小记录无效：{}".format(path))
        if not isinstance(digest, str) or len(digest) != 64:
            raise BackupError("备份文件校验值无效：{}".format(path))


def _validate_archive_name(name):
    if not isinstance(name, str) or not name:
        raise BackupError("备份包包含无效文件名。")
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != name:
        raise BackupError("备份包包含不安全路径：{}".format(name))
    if pure.parts[0] not in ("manifest.json", "reconciliation.db", "uploads"):
        raise BackupError("备份包包含未知文件：{}".format(name))
    if pure.parts[0] in ("manifest.json", "reconciliation.db") and len(pure.parts) != 1:
        raise BackupError("备份包文件路径不正确：{}".format(name))


def _safe_data_dir(data_dir):
    path = Path(data_dir).expanduser().resolve()
    anchor = Path(path.anchor)
    if path == anchor or path.parent == path or len(path.parts) < 3:
        raise BackupError("数据目录范围过大，已停止操作。")
    return path


def _hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_archive_entry(archive, name):
    digest = hashlib.sha256()
    with archive.open(name, "r") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _process_is_running(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _rollback_restore(stage, data_dir, recovery_path):
    if recovery_path and recovery_path.exists() and not data_dir.exists():
        recovery_path.replace(data_dir)
    if stage.exists():
        shutil.rmtree(str(stage))


def _remove_file_if_exists(path):
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
