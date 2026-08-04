"""Verified SQLite Backup API snapshots taken before authoring migration."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.persistence.errors import V2PersistenceError
from app.schemas.v2_persistence import DatabaseBackupReport

_PRE_AUTHORING_REVISION = "20260720_01"


def ensure_pre_authoring_database_backup(
    data_dir: Path, database_path: Path
) -> DatabaseBackupReport:
    """Create one immutable verified Backup API snapshot when it is required."""

    backup_dir = data_dir / "v2" / "migration-backups" / "database"
    backup_path = backup_dir / "adcraft.pre-project-authoring.sqlite3"
    manifest_path = backup_dir / "adcraft.pre-project-authoring.manifest.json"
    if backup_path.exists() or manifest_path.exists():
        return _existing_backup_report(database_path, backup_path, manifest_path)
    if not database_path.is_file() or _current_revision(database_path) != _PRE_AUTHORING_REVISION:
        return DatabaseBackupReport(status="not_required", database_path=database_path)

    backup_dir.mkdir(parents=True, exist_ok=True)
    temporary_backup = backup_dir / f".{backup_path.name}.tmp"
    temporary_manifest = backup_dir / f".{manifest_path.name}.tmp"
    try:
        _create_sqlite_backup(database_path, temporary_backup)
        _verify_sqlite_backup(temporary_backup)
        source_hash = _sha256(database_path)
        backup_hash = _sha256(temporary_backup)
        manifest = {
            "source_revision": _PRE_AUTHORING_REVISION,
            "source_sha256": source_hash,
            "backup_sha256": backup_hash,
            "created_at": _utc_now(),
        }
        temporary_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        _fsync_file(temporary_backup)
        _fsync_file(temporary_manifest)
        os.replace(temporary_backup, backup_path)
        os.replace(temporary_manifest, manifest_path)
    except V2PersistenceError:
        raise
    except (OSError, sqlite3.Error, ValueError, json.JSONDecodeError) as error:
        raise _backup_error() from error
    finally:
        temporary_backup.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)

    return DatabaseBackupReport(
        status="created",
        database_path=database_path,
        backup_path=backup_path,
        manifest_path=manifest_path,
        source_sha256=source_hash,
        backup_sha256=backup_hash,
    )


def _existing_backup_report(
    database_path: Path,
    backup_path: Path,
    manifest_path: Path,
) -> DatabaseBackupReport:
    if not backup_path.is_file() or not manifest_path.is_file():
        raise _backup_error()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        backup_hash = _sha256(backup_path)
        if (
            not isinstance(manifest, dict)
            or manifest.get("source_revision") != _PRE_AUTHORING_REVISION
            or manifest.get("backup_sha256") != backup_hash
            or not isinstance(manifest.get("source_sha256"), str)
        ):
            raise _backup_error()
        _verify_sqlite_backup(backup_path)
    except V2PersistenceError:
        raise
    except (OSError, sqlite3.Error, ValueError, json.JSONDecodeError) as error:
        raise _backup_error() from error
    return DatabaseBackupReport(
        status="existing",
        database_path=database_path,
        backup_path=backup_path,
        manifest_path=manifest_path,
        source_sha256=str(manifest["source_sha256"]),
        backup_sha256=backup_hash,
    )


def _current_revision(database_path: Path) -> str | None:
    try:
        with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.Error:
        return None
    return None if row is None else str(row[0])


def _create_sqlite_backup(source_path: Path, destination_path: Path) -> None:
    with sqlite3.connect(f"file:{source_path}?mode=ro", uri=True) as source:
        with sqlite3.connect(destination_path) as destination:
            source.backup(destination)


def _verify_sqlite_backup(backup_path: Path) -> None:
    with sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True) as connection:
        result = connection.execute("PRAGMA quick_check").fetchone()
    if result is None or str(result[0]).lower() != "ok":
        raise _backup_error()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as source:
        os.fsync(source.fileno())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backup_error() -> V2PersistenceError:
    return V2PersistenceError(
        "v2_persistence_backup_failed",
        "V2 persistence backup failed.",
        stage="backup",
    )
