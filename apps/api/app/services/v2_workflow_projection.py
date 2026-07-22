"""Deterministic operational projection of immutable V2 authoring state."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.persistence.errors import V2PersistenceError
from app.persistence.workflow_authoring_repository import WorkflowAuthoringRepository
from app.schemas.workflow_v2 import WorkflowV2
from app.schemas.workflow_v2_authoring import CurrentWorkflowAuthoringState
from app.services.v2_workflow_lock import v2_workflow_lock
from app.services.v2_workflow_read_model import (
    apply_operational_overlay,
    operational_overlay_from_workflow,
    workflow_from_authoring,
)
from app.services.v2_workflow_store import V2WorkflowStore


class ProjectionResult(BaseModel):
    """Bounded result of an authoring-to-projection render attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_id: str
    revision_no: int
    state: str


class WorkflowProjectionService:
    """The only service that writes post-import V2 Workflow projections."""

    def __init__(self, data_dir: Path, authoring_repository: WorkflowAuthoringRepository) -> None:
        self._data_dir = data_dir
        self._authoring_repository = authoring_repository
        self._store = V2WorkflowStore(data_dir)

    def rebuild(self, workflow_id: str) -> ProjectionResult:
        """Render current SQLite authoring with any valid existing runtime overlay."""

        current = self._authoring_repository.load_current(workflow_id)
        try:
            with v2_workflow_lock(self._data_dir, workflow_id):
                workflow = _workflow_from_current_authoring(current)
                source = self._store.load_optional_projection_source(workflow_id)
                if source is not None:
                    workflow = apply_operational_overlay(
                        workflow,
                        operational_overlay_from_workflow(source),
                    )
                self._store.write_projection_atomic(workflow)
            self._authoring_repository.mark_projection_clean(
                workflow_id,
                current.semantic_revision_no,
            )
        except Exception as error:
            self._authoring_repository.mark_projection_dirty(
                workflow_id,
                error_code="workflow_projection_write_failed",
                error_summary="Workflow projection could not be written.",
            )
            raise V2PersistenceError(
                "workflow_projection_not_ready",
                "Workflow projection is not ready.",
                stage="projection",
            ) from error
        return ProjectionResult(
            workflow_id=workflow_id,
            revision_no=current.semantic_revision_no,
            state="clean",
        )

    def ensure_ready(self, workflow_id: str) -> ProjectionResult:
        """Repair the projection when its current revision is absent or dirty."""

        current = self._authoring_repository.load_current(workflow_id)
        if (
            current.projection_state == "clean"
            and current.projection_revision_no == current.semantic_revision_no
            and self._store.load_optional_projection_source(workflow_id) is not None
        ):
            return ProjectionResult(
                workflow_id=workflow_id,
                revision_no=current.semantic_revision_no,
                state="clean",
            )
        return self.rebuild(workflow_id)

    def save_operational_overlay(
        self,
        workflow: WorkflowV2,
        *,
        expected_revision_no: int,
    ) -> ProjectionResult:
        """Rebase a full runtime source on current authoring without a revision commit."""

        current = self._authoring_repository.load_current(workflow.workflow_id)
        try:
            with v2_workflow_lock(self._data_dir, workflow.workflow_id):
                rebased = apply_operational_overlay(
                    _workflow_from_current_authoring(current),
                    operational_overlay_from_workflow(workflow),
                )
                self._store.write_projection_atomic(rebased)
            self._authoring_repository.mark_projection_clean(
                workflow.workflow_id,
                current.semantic_revision_no,
            )
        except Exception as error:
            self._authoring_repository.mark_projection_dirty(
                workflow.workflow_id,
                error_code="workflow_projection_write_failed",
                error_summary="Workflow projection could not be written.",
            )
            raise V2PersistenceError(
                "workflow_projection_not_ready",
                "Workflow projection is not ready.",
                stage="projection",
            ) from error
        return ProjectionResult(
            workflow_id=workflow.workflow_id,
            revision_no=current.semantic_revision_no,
            state="clean" if expected_revision_no == current.semantic_revision_no else "rebased",
        )


def _workflow_from_current_authoring(current: CurrentWorkflowAuthoringState) -> WorkflowV2:
    """Render authoring state with the persistent Workflow identity fields."""

    return workflow_from_authoring(current.revision.document).model_copy(
        update={
            "project_id": current.project_id,
            "state_version": current.state_version,
            "semantic_revision_no": current.semantic_revision_no,
            "created_at": current.created_at,
            "updated_at": current.updated_at,
        }
    )
