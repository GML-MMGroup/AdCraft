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
        self._repository.reclaim_unreferenced_assets()
        for manifest in self._repository.cleanup_candidates():
            self.cleanup(manifest)

    def cleanup(self, manifest: ProjectDeletionManifestV1) -> bool:
        completed = True
        for key in manifest.storage_keys:
            try:
                if not key.startswith("assets/objects/sha256/"):
                    raise ValueError("Deletion manifest contains an unsupported object location.")
                path = self._storage.resolve_local_path(key)
                if path != self._root / key or path.is_symlink():
                    raise ValueError("Deletion cleanup does not follow symbolic links.")
                if not path.exists():
                    continue
                # Recheck content-addressed sharing immediately before unlinking.
                # A different logical Asset may own the same object bytes.
                with self._repository.database.engine.connect() as connection:
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
                    if not storage_key_is_referenced(connection, key):
                        path.unlink(missing_ok=True)
                    else:
                        completed = False
                    connection.commit()
            except Exception:
                completed = False
                logger.exception(
                    "Project object cleanup remains pending: project_id=%s, key=%s",
                    manifest.project_id,
                    key,
                )
        directories = (
            *(
                (category, workflow)
                for workflow in manifest.workflow_ids
                for category in ("workflows", "runs")
            ),
            *(("renditions", asset) for asset in manifest.asset_ids),
        )
        for category, identity in directories:
            try:
                self._remove_directory(category, identity)
            except Exception:
                completed = False
                logger.exception(
                    "Project directory cleanup remains pending: project_id=%s, category=%s",
                    manifest.project_id,
                    category,
                )
        try:
            # A recovery worker may have added newly unreferenced assets while
            # this pass ran. Never acknowledge work absent from this snapshot.
            recorded = self._repository.record_cleanup(manifest, completed=completed)
            return completed and recorded
        except Exception:
            logger.exception(
                "Project cleanup acknowledgement remains pending: project_id=%s",
                manifest.project_id,
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
