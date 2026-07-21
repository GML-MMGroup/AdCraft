"""Explicit startup bootstrap for the V2 SQLite persistence boundary."""

from __future__ import annotations

from filelock import FileLock, Timeout

from app.core.config import Settings
from app.persistence.database import create_v2_database, resolve_v2_database_path
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.schema import upgrade_v2_schema
from app.schemas.v2_persistence import PersistenceBootstrapState
from app.services.v2_event_import import V2EventImportService

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
            schema_revision = upgrade_v2_schema(database)
            repository = EventRepository(database)
            report = V2EventImportService(
                self._settings.media_data_dir,
                repository,
            ).import_if_required()
            return PersistenceBootstrapState(
                database_path=resolve_v2_database_path(self._settings.media_data_dir),
                schema_revision=schema_revision,
                data_migration_name=report.migration_name,
            )
        finally:
            database.dispose()
