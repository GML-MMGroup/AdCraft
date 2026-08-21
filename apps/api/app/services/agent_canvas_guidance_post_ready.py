"""Read-only Guidance admission gate for current post-Ready settlement."""

from __future__ import annotations

from pydantic import ValidationError

from app.persistence.agent_canvas_result_commit_repository import (
    AgentCanvasResultCommitRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import AgentCanvasWorkflowV2, CanvasNodeV2
from app.schemas.agent_canvas_creative_session import GuidedSessionStateV2
from app.schemas.agent_canvas_guided_checkpoint import GuidedCheckpointOriginV1
from app.schemas.agent_canvas_post_ready_checkpoint import CanvasPostReadyCheckpointV2
from app.services.agent_canvas_post_ready_checkpoint import (
    AgentCanvasPostReadyCheckpointService,
)


class GuidancePostReadyGate:
    """Block Guidance only on the current guided checkpoint lineage."""

    def __init__(
        self,
        *,
        result_commits: AgentCanvasResultCommitRepository,
        checkpoints: AgentCanvasPostReadyCheckpointService,
    ) -> None:
        self._result_commits = result_commits
        self._checkpoints = checkpoints

    def evaluate(
        self,
        workflow_id: str,
        session: GuidedSessionStateV2,
        workflow: AgentCanvasWorkflowV2,
    ) -> CanvasPostReadyCheckpointV2 | None:
        journey = session.journey
        if journey.stage != "storyboard_grids":
            return None
        matched: list[tuple[CanvasNodeV2, GuidedCheckpointOriginV1]] = []
        for node in sorted(workflow.nodes, key=lambda item: item.node_id):
            raw_origin = node.metadata.get("guided_checkpoint")
            if raw_origin is None:
                continue
            try:
                origin = GuidedCheckpointOriginV1.model_validate(raw_origin)
            except ValidationError:
                if node.creative_role == "storyboard_sequence" and node.status == "ready":
                    self._raise_unavailable(
                        node_id=node.node_id,
                        stage_revision=journey.stage_revision,
                    )
                continue
            if (
                origin.guidance_session_id == session.session_id
                and origin.stage_revision == journey.stage_revision
            ):
                matched.append((node, origin))
        if not matched:
            return None
        completed: CanvasPostReadyCheckpointV2 | None = None
        for node, origin in matched:
            if node.status in {"draft", "working"}:
                self._raise_pending(origin, execution_id=None)
            if node.status != "ready":
                continue
            execution_id = self._result_commits.find_latest_execution_id(
                workflow_id=workflow_id,
                node_id=node.node_id,
            )
            if execution_id is None:
                self._raise_unavailable(
                    node_id=node.node_id,
                    stage_revision=journey.stage_revision,
                    checkpoint_id=origin.checkpoint_id,
                )
            checkpoint = self._checkpoints.get(workflow_id, execution_id)
            if checkpoint.status == "pending":
                self._raise_pending(origin, execution_id=execution_id)
            if checkpoint.status == "failed":
                source_error = checkpoint.error
                raise V2PersistenceError(
                    "post_ready_progression_failed",
                    "Guided post-Ready progression failed.",
                    stage="guidance_post_ready_gate",
                    details={
                        "checkpoint_id": origin.checkpoint_id,
                        "execution_id": execution_id,
                        "status": checkpoint.status,
                        "journey_stage": origin.stage,
                        "stage_revision": origin.stage_revision,
                        "error_code": (
                            source_error.code if source_error else "post_ready_effect_failed"
                        ),
                        "error_message": (
                            source_error.message if source_error else "A post-Ready effect failed."
                        ),
                        "retryable": source_error.retryable if source_error else False,
                    },
                )
            completed = checkpoint
        return completed

    @staticmethod
    def _raise_pending(
        origin: GuidedCheckpointOriginV1,
        *,
        execution_id: str | None,
    ) -> None:
        raise V2PersistenceError(
            "guidance_post_ready_pending",
            "Guided post-Ready progression is still pending.",
            stage="guidance_post_ready_gate",
            details={
                "checkpoint_id": origin.checkpoint_id,
                "execution_id": execution_id,
                "status": "pending",
                "journey_stage": origin.stage,
                "stage_revision": origin.stage_revision,
                "retry_after_seconds": 1,
                "retryable": True,
            },
        )

    @staticmethod
    def _raise_unavailable(
        *,
        node_id: str,
        stage_revision: int,
        checkpoint_id: str | None = None,
    ) -> None:
        raise V2PersistenceError(
            "post_ready_checkpoint_unavailable",
            "Guided post-Ready checkpoint lineage is unavailable.",
            stage="guidance_post_ready_gate",
            details={
                "checkpoint_id": checkpoint_id,
                "node_id": node_id,
                "journey_stage": "storyboard_grids",
                "stage_revision": stage_revision,
                "retryable": False,
            },
        )
