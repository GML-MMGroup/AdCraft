"""Application service for V2 Project catalog commands and queries."""

from __future__ import annotations

from pathlib import Path

from app.persistence.project_repository import ProjectRepository
from app.schemas.workflow_v2 import WorkflowV2
from app.schemas.workflow_v2_projects import (
    ProjectRecord,
    ProjectStatusV2,
    ProjectV2,
    ProjectV2ListResponse,
    ProjectV2Summary,
)
from app.services.v2_workflow_authoring import (
    WorkflowAuthoringRuntime,
    create_workflow_authoring_runtime,
)


class V2ProjectService:
    """Compose Project metadata with its one owned Workflow."""

    def __init__(self, data_dir: Path) -> None:
        self._runtime: WorkflowAuthoringRuntime = create_workflow_authoring_runtime(data_dir)
        self._projects = ProjectRepository(self._runtime.database)

    def close(self) -> None:
        self._runtime.database.dispose()

    def list_projects(
        self,
        *,
        status: ProjectStatusV2,
        limit: int,
        cursor: str | None,
    ) -> ProjectV2ListResponse:
        page = self._projects.list(status=status, limit=limit, cursor=cursor)
        return ProjectV2ListResponse(
            items=tuple(self._summary(record) for record in page.items),
            next_cursor=page.next_cursor,
        )

    def get_project(self, project_id: str) -> ProjectV2:
        return self._detail(self._projects.get(project_id))

    def get_workflow(self, project_id: str) -> WorkflowV2:
        workflow_id, _ = self._projects.workflow_identity(project_id)
        return self._runtime.read_model.assemble(workflow_id)

    def update_project(
        self,
        project_id: str,
        *,
        expected_version: int,
        changes: dict[str, object],
    ) -> ProjectV2:
        return self._detail(
            self._projects.update(
                project_id,
                expected_version=expected_version,
                changes=changes,
            )
        )

    def trash_project(self, project_id: str, *, expected_version: int) -> ProjectV2:
        return self._detail(self._projects.trash(project_id, expected_version=expected_version))

    def restore_project(self, project_id: str, *, expected_version: int) -> ProjectV2:
        return self._detail(self._projects.restore(project_id, expected_version=expected_version))

    def _summary(self, record: ProjectRecord) -> ProjectV2Summary:
        workflow_id, _ = self._projects.workflow_identity(record.project_id)
        return ProjectV2Summary(
            **record.model_dump(exclude={"description", "created_at", "deleted_at"}),
            workflow_id=workflow_id,
        )

    def _detail(self, record: ProjectRecord) -> ProjectV2:
        workflow_id, revision_no = self._projects.workflow_identity(record.project_id)
        return ProjectV2(
            **record.model_dump(),
            workflow_id=workflow_id,
            semantic_revision_no=revision_no,
        )
