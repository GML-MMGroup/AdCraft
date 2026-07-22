"""Explicit startup bootstrap for the V2 SQLite persistence boundary."""

from __future__ import annotations

from filelock import FileLock, Timeout

from app.core.config import Settings
from app.persistence.backup import ensure_pre_authoring_database_backup
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import create_v2_database, resolve_v2_database_path
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.project_repository import ProjectRepository
from app.persistence.schema import upgrade_v2_schema
from app.persistence.workflow_authoring_repository import WorkflowAuthoringRepository
from app.schemas.v2_persistence import PersistenceBootstrapState
from app.services.v2_event_import import V2EventImportService
from app.services.v2_asset_metadata_import import V2AssetMetadataImportService
from app.services.v2_workflow_authoring_import import WorkflowAuthoringImportService
from app.services.v2_workflow_authoring_projector import WorkflowAuthoringProjector

_LOCK_TIMEOUT_SECONDS = 5.0


class PersistenceBootstrapService:
    """Bootstrap the V2 event database before V2 runtime recovery begins."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def bootstrap(self) -> PersistenceBootstrapState:
        """Create and verify the V2 event persistence boundary exactly once per startup."""

        data_dir = self._settings.media_data_dir
        v2_dir = data_dir / "v2"
        v2_dir.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(v2_dir / ".persistence.lock"))
        try:
            with lock.acquire(timeout=_LOCK_TIMEOUT_SECONDS):
                return self._bootstrap_locked()
        except Timeout as error:
            raise V2PersistenceError(
                "v2_persistence_lock_timeout",
                "V2 persistence bootstrap timed out.",
                stage="lock",
            ) from error

    def _bootstrap_locked(self) -> PersistenceBootstrapState:
        database = create_v2_database(self._settings.media_data_dir)
        try:
            database_backup = ensure_pre_authoring_database_backup(
                self._settings.media_data_dir,
                resolve_v2_database_path(self._settings.media_data_dir),
            )
            schema_revision = upgrade_v2_schema(database)
            event_repository = EventRepository(database)
            report = V2EventImportService(
                self._settings.media_data_dir,
                event_repository,
            ).import_if_required()
            project_repository = ProjectRepository(database)
            authoring_repository = WorkflowAuthoringRepository(
                database,
                project_repository,
                event_repository,
            )
            authoring_report = WorkflowAuthoringImportService(
                self._settings.media_data_dir,
                project_repository,
                authoring_repository,
                WorkflowAuthoringProjector(),
            ).import_all()
            V2AssetMetadataImportService(
                self._settings.media_data_dir,
                V2AssetLibraryRepository(database),
                event_repository,
            ).import_if_required()
            return PersistenceBootstrapState(
                database_path=resolve_v2_database_path(self._settings.media_data_dir),
                schema_revision=schema_revision,
                database_backup_status=database_backup.status,
                data_migration_name=report.migration_name,
                workflow_imported_count=authoring_report.imported_count,
                workflow_quarantined_count=authoring_report.quarantined_count,
            )
        finally:
            database.dispose()
