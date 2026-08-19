"""Derive bounded post-Ready checkpoint state from durable runtime rows."""

from __future__ import annotations

from collections import Counter

from app.persistence.agent_canvas_post_ready_checkpoint_repository import (
    AgentCanvasPostReadyCheckpointRepository,
)
from app.schemas.agent_canvas_errors import CanvasNodeErrorV2
from app.schemas.agent_canvas_post_ready_checkpoint import (
    CanvasPostReadyCheckpointV2,
    CanvasPostReadyEffectCountsV2,
    CanvasPostReadyEffectSummaryV2,
)


class AgentCanvasPostReadyCheckpointService:
    """Project one execution's terminal and post-Ready settlement state."""

    def __init__(self, repository: AgentCanvasPostReadyCheckpointRepository) -> None:
        self._repository = repository

    def get(self, workflow_id: str, execution_id: str) -> CanvasPostReadyCheckpointV2:
        snapshot = self._repository.get(workflow_id, execution_id)
        effects = tuple(
            CanvasPostReadyEffectSummaryV2(
                effect_id=effect.effect_id,
                effect_type=effect.effect_type,
                node_id=effect.node_id,
                status=effect.status,
                attempt_no=effect.attempt_no,
                error=effect.error,
                updated_at=effect.updated_at,
            )
            for effect in snapshot.effects
        )
        counts_by_status = Counter(effect.status for effect in effects)
        counts = CanvasPostReadyEffectCountsV2(
            total=len(effects),
            queued=counts_by_status["queued"],
            running=counts_by_status["running"],
            completed=counts_by_status["completed"],
            failed=counts_by_status["failed"],
        )
        status = "completed"
        error = None
        if snapshot.execution_status in {"queued", "running", "waiting"}:
            status = "pending"
        elif snapshot.execution_status in {"failed", "cancelled"}:
            status = "failed"
            error = CanvasNodeErrorV2(
                code=f"execution_{snapshot.execution_status}",
                message=f"Execution {snapshot.execution_status} before settlement.",
                retryable=False,
            )
        elif counts.failed:
            status = "failed"
            error = next(effect.error for effect in effects if effect.status == "failed")
            error = error or CanvasNodeErrorV2(
                code="post_ready_effect_failed",
                message="A post-Ready effect failed.",
                retryable=False,
            )
        elif counts.queued or counts.running:
            status = "pending"
        updated_at = max(
            (snapshot.updated_at, *(effect.updated_at for effect in effects)),
        )
        return CanvasPostReadyCheckpointV2(
            checkpoint_id=f"post-ready:{execution_id}",
            workflow_id=workflow_id,
            execution_id=execution_id,
            execution_status=snapshot.execution_status,
            status=status,
            counts=counts,
            effects=effects,
            error=error,
            updated_at=updated_at,
        )
