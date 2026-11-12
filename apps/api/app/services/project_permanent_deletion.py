"""Recoverable filesystem cleanup after authoritative Project deletion."""

from __future__ import annotations

import logging
from pathlib import Path
import shutil

from app.persistence.database import V2Database
from app.persistence.project_deletion_repository import (
    ProjectDeletionRepository,
    storage_key_is_referenced,
)
from app.schemas.project_deletion import ProjectDeletionManifestV1
from app.services.v2_storage_adapter import StorageAdapter


logger = logging.getLogger(__name__)


class ProjectPermanentDeletionService:
    def __init__(self, database: V2Database, data_dir: Path) -> None:
        self._repository = ProjectDeletionRepository(database)
        self._root = data_dir.resolve()
        self._storage = StorageAdapter(self._root)

    def delete(self, project_id: str, *, expected_version: int) -> None:
        manifest = self._repository.delete(project_id, expected_version=expected_version)
        self.cleanup(manifest)

    def recover_pending(self) -> None:
        for manifest in self._repository.pending():
            self.cleanup(manifest)

    def cleanup(self, manifest: ProjectDeletionManifestV1) -> bool:
        try:
            for key in manifest.storage_keys:
                if not key.startswith("assets/objects/sha256/"):
                    raise ValueError("Deletion manifest contains an unsupported object location.")
                # Recheck content-addressed sharing immediately before unlinking.
                # A different logical Asset may own the same object bytes.
                with self._repository.database.engine.connect() as connection:
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
                    if not storage_key_is_referenced(connection, key):
                        path = self._storage.resolve_local_path(key)
                        if path != self._root / key or path.is_symlink():
                            raise ValueError("Deletion cleanup does not follow symbolic links.")
                        path.unlink(missing_ok=True)
                    connection.commit()
            for workflow_id in manifest.workflow_ids:
                self._remove_directory("workflows", workflow_id)
                self._remove_directory("runs", workflow_id)
            for asset_id in manifest.asset_ids:
                self._remove_directory("renditions", asset_id)
            self._repository.complete(manifest.project_id)
            return True
        except Exception:
            logger.exception(
                "Project deletion cleanup remains pending: project_id=%s", manifest.project_id
            )
            return False

    def _remove_directory(self, category: str, identity: str) -> None:
        if not identity or identity in {".", ".."} or Path(identity).name != identity:
            raise ValueError("Deletion manifest contains an invalid identity.")
        path = self._root / "v2" / category / identity
        if path.resolve() != path or path.is_symlink():
            raise ValueError("Deletion cleanup does not follow symbolic links.")
        if path.exists():
            shutil.rmtree(path)
