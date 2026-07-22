"""Domain facade for semantic V2 Workflow authoring commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.persistence.database import V2Database, create_v2_database
from app.persistence.event_repository import EventRepository
from app.persistence.project_repository import ProjectRepository
from app.persistence.workflow_authoring_repository import WorkflowAuthoringRepository
from app.schemas.workflow_v2 import WorkflowV2
from app.schemas.workflow_v2_authoring import (
    WorkflowRevisionChangeSource,
    WorkflowRevisionCommitRequest,
)
from app.schemas.workflow_v2_projects import ProjectCreate
from app.services.v2_workflow_authoring_projector import WorkflowAuthoringProjector
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_workflow_projection import WorkflowProjectionService
from app.services.v2_workflow_read_model import WorkflowV2ReadModelAssembler
from app.services.v2_workflow_store import V2WorkflowStore


@dataclass(frozen=True)
class WorkflowAuthoringRuntime:
    """Shared SQLite authoring services for one V2 data root."""

    database: V2Database
    repository: WorkflowAuthoringRepository
    projection: WorkflowProjectionService
    read_model: WorkflowV2ReadModelAssembler
    service: "WorkflowAuthoringService"


def create_workflow_authoring_runtime(data_dir: Path) -> WorkflowAuthoringRuntime:
    """Compose focused authoring services without opening asset or media stores."""

    database = create_v2_database(data_dir)
    repository = WorkflowAuthoringRepository(
        database,
        ProjectRepository(database),
        EventRepository(database),
    )
    projection = WorkflowProjectionService(data_dir, repository)
    read_model = WorkflowV2ReadModelAssembler(
        repository,
        V2WorkflowStore(data_dir),
        V2AssetStoreService(data_dir),
    )
    service = WorkflowAuthoringService(
        repository,
        WorkflowAuthoringProjector(),
        projection,
        read_model,
    )
    return WorkflowAuthoringRuntime(
        database=database,
        repository=repository,
        projection=projection,
        read_model=read_model,
        service=service,
    )


class WorkflowAuthoringService:
    """Coordinates authoring transactions and post-commit projection repair."""

    def __init__(
        self,
        repository: WorkflowAuthoringRepository,
        projector: WorkflowAuthoringProjector,
        projection: WorkflowProjectionService,
        read_model: WorkflowV2ReadModelAssembler,
    ) -> None:
        self._repository = repository
        self._projector = projector
        self._projection = projection
        self._read_model = read_model

    def create_planned_workflow(
        self,
        workflow: WorkflowV2,
        *,
        source: WorkflowRevisionChangeSource = "create",
    ) -> WorkflowV2:
        """Atomically create Project, Workflow, Revision 1, and its event."""

        document = self._projector.project(workflow)
        project_id = workflow.project_id or f"proj_{uuid4().hex[:12]}"
        result = self._repository.create_initial(
            project=ProjectCreate(
                project_id=project_id,
                name=workflow.name,
                description=workflow.description,
                created_at=workflow.created_at,
                updated_at=workflow.updated_at,
            ),
            workflow_id=workflow.workflow_id,
            document=document,
            content_hash=self._projector.content_hash(document),
            change_source=source,
        )
        self._rebuild_after_commit(workflow.workflow_id)
        self._projection.save_operational_overlay(
            workflow,
            expected_revision_no=result.revision_no,
        )
        return self._read_model.assemble(workflow.workflow_id)

    def commit_semantic_workflow(
        self,
        workflow: WorkflowV2,
        *,
        expected_version: int,
        source: WorkflowRevisionChangeSource,
        source_execution_id: str | None = None,
    ) -> WorkflowV2:
        """Commit one fully-applied semantic Workflow command."""

        current = self._repository.load_current(workflow.workflow_id)
        document = self._projector.project(workflow)
        result = self._repository.commit_revision(
            WorkflowRevisionCommitRequest(
                project_id=current.project_id,
                workflow_id=workflow.workflow_id,
                expected_state_version=expected_version,
                document=document,
                content_hash=self._projector.content_hash(document),
                change_source=source,
                source_execution_id=source_execution_id,
            )
        )
        if result.status == "committed":
            self._rebuild_after_commit(workflow.workflow_id)
        return self._read_model.assemble(workflow.workflow_id)

    def commit_execution_result(
        self,
        workflow: WorkflowV2,
        *,
        expected_version: int,
        source_execution_id: str,
    ) -> WorkflowV2:
        """Commit one execution-produced semantic result with its execution identity."""

        return self.commit_semantic_workflow(
            workflow,
            expected_version=expected_version,
            source="execution_result",
            source_execution_id=source_execution_id,
        )

    def restore_revision(
        self,
        workflow_id: str,
        revision_no: int,
        *,
        expected_version: int,
    ) -> WorkflowV2:
        """Restore history into a new immutable revision and rebuild its projection."""

        self._repository.restore_revision(workflow_id, revision_no, expected_version)
        self._rebuild_after_commit(workflow_id)
        return self._read_model.assemble(workflow_id)

    def _rebuild_after_commit(self, workflow_id: str) -> None:
        """Attempt projection repair after the database transaction has committed."""

        try:
            self._projection.rebuild(workflow_id)
        except Exception:
            # The authoring commit remains durable and projection is already marked dirty.
            return
