"""Independent, idempotent import of legacy V2 Workflow authoring files."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from pydantic import ValidationError

from app.persistence.project_repository import ProjectRepository
from app.persistence.workflow_authoring_repository import WorkflowAuthoringRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.v2_persistence import (
    DataMigrationCompletion,
    WorkflowAuthoringImportItemResult,
    WorkflowAuthoringImportReport,
)
from app.schemas.workflow_v2 import WorkflowV2
from app.schemas.workflow_v2_projects import ProjectCreate
from app.services.agent_trace import utc_now
from app.services.v2_workflow_authoring_projector import WorkflowAuthoringProjector

_MIGRATION_PREFIX = "v2_workflow_authoring_import_v1:"


class WorkflowAuthoringImportService:
    """Import each workflow independently without writing source projections."""

    def __init__(
        self,
        data_dir: Path,
        project_repository: ProjectRepository,
        authoring_repository: WorkflowAuthoringRepository,
        projector: WorkflowAuthoringProjector,
    ) -> None:
        if project_repository.database is not authoring_repository.database:
            raise ValueError("V2 authoring import repositories must share one V2Database instance.")
        self._data_dir = data_dir
        self._projects = project_repository
        self._authoring = authoring_repository
        self._projector = projector

    def import_all(self) -> WorkflowAuthoringImportReport:
        """Import each discovered workflow while quarantining failures independently."""

        return WorkflowAuthoringImportReport(
            items=tuple(
                self.import_one(path.parent.name, path) for path in self.discover_workflow_paths()
            )
        )

    def import_one(
        self,
        workflow_id: str,
        source_path: Path,
    ) -> WorkflowAuthoringImportItemResult:
        """Import one legacy Workflow JSON document or record a bounded quarantine."""

        migration_name = f"{_MIGRATION_PREFIX}{workflow_id}"
        if self._authoring.event_repository.migration_status(migration_name) == "completed":
            return WorkflowAuthoringImportItemResult(workflow_id=workflow_id, status="skipped")
        try:
            self._authoring.load_current(workflow_id)
        except V2PersistenceError as error:
            if error.code != "workflow_not_found":
                raise
        else:
            return WorkflowAuthoringImportItemResult(workflow_id=workflow_id, status="skipped")
        try:
            source_bytes = source_path.read_bytes()
            source_sha256 = hashlib.sha256(source_bytes).hexdigest()
            workflow = WorkflowV2.model_validate_json(source_bytes)
            if workflow.workflow_id != workflow_id:
                raise ValueError("workflow_id does not match its source directory")
            document = self._projector.project(workflow)
            backup_relative_path = self._publish_first_backup(workflow_id, source_bytes)
            project_id = _project_id_for_workflow(workflow_id)
            committed = self._authoring.create_initial(
                project=ProjectCreate(
                    project_id=project_id,
                    name=workflow.name,
                    description=workflow.description,
                    created_at=workflow.created_at,
                    updated_at=workflow.updated_at,
                ),
                workflow_id=workflow_id,
                document=document,
                content_hash=self._projector.content_hash(document),
                change_source="migration",
                migration_completion=DataMigrationCompletion(
                    migration_name=migration_name,
                    source_count=1,
                    imported_count=1,
                    completed_at=utc_now().isoformat(),
                    details={"workflow_id": workflow_id, "project_id": project_id},
                ),
            )
            return WorkflowAuthoringImportItemResult(
                workflow_id=workflow_id,
                status="imported",
                project_id=project_id,
                revision_id=committed.revision_id,
                source_sha256=source_sha256,
                backup_relative_path=backup_relative_path,
            )
        except ValidationError as error:
            return self._quarantine(
                workflow_id,
                migration_name,
                source_path,
                validation_paths=_validation_paths(error),
            )
        except V2PersistenceError:
            raise
        except (OSError, ValueError):
            return self._quarantine(workflow_id, migration_name, source_path, validation_paths=())

    def discover_workflow_paths(self) -> list[Path]:
        """Return legacy source projections in stable workflow-id order."""

        root = self._data_dir / "v2" / "workflows"
        if not root.is_dir():
            return []
        return sorted(
            (
                path / "workflow.json"
                for path in root.iterdir()
                if path.is_dir() and (path / "workflow.json").is_file()
            ),
            key=lambda path: path.parent.name,
        )

    def _publish_first_backup(self, workflow_id: str, source_bytes: bytes) -> str:
        relative_path = (
            Path("v2")
            / "migration-backups"
            / "workflows"
            / workflow_id
            / "workflow.pre-sqlite.json"
        )
        backup_path = self._data_dir / relative_path
        if backup_path.exists():
            return relative_path.as_posix()
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = backup_path.with_name(f".{backup_path.name}.tmp")
        try:
            temporary_path.write_bytes(source_bytes)
            with temporary_path.open("rb") as temporary_file:
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, backup_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        return relative_path.as_posix()

    def _quarantine(
        self,
        workflow_id: str,
        migration_name: str,
        source_path: Path,
        *,
        validation_paths: tuple[str, ...],
    ) -> WorkflowAuthoringImportItemResult:
        relative_path = source_path.relative_to(self._data_dir).as_posix()
        self._authoring.event_repository.record_migration_failure(
            migration_name,
            details={
                "workflow_id": workflow_id,
                "status": "quarantined",
                "source_path": relative_path,
                "validation_paths": list(validation_paths),
                "error_code": "workflow_import_quarantined",
                "error_summary": "Workflow import could not be validated.",
                "recorded_at": utc_now().isoformat(),
            },
        )
        return WorkflowAuthoringImportItemResult(
            workflow_id=workflow_id,
            status="quarantined",
            error_code="workflow_import_quarantined",
            error_summary="Workflow import could not be validated.",
            validation_paths=validation_paths,
        )


def _project_id_for_workflow(workflow_id: str) -> str:
    return f"proj_{hashlib.sha256(workflow_id.encode('utf-8')).hexdigest()[:12]}"


def _validation_paths(error: ValidationError) -> tuple[str, ...]:
    return tuple(".".join(str(part) for part in item["loc"])[:256] for item in error.errors()[:20])
