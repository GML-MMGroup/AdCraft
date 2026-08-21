"""Read-only SQLite snapshot for Agent Canvas post-Ready settlement."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.models import (
    AgentCanvasExecutionResultCommitRow,
    AgentCanvasExecutionRow,
    AgentCanvasPostReadyEffectRow,
)
from app.schemas.agent_canvas_errors import CanvasNodeErrorV2
from app.schemas.agent_canvas_post_ready_checkpoint import (
    PostReadyEffectStatusV2,
    PostReadyEffectTypeV2,
)
from app.schemas.agent_canvas_runtime import CanvasExecutionStatusV2


@dataclass(frozen=True)
class PostReadyEffectSnapshot:
    effect_id: str
    effect_type: PostReadyEffectTypeV2
    node_id: str
    status: PostReadyEffectStatusV2
    attempt_no: int
    error: CanvasNodeErrorV2 | None
    updated_at: datetime


@dataclass(frozen=True)
class PostReadyExecutionSnapshot:
    workflow_id: str
    execution_id: str
    execution_status: CanvasExecutionStatusV2
    updated_at: datetime
    effects: tuple[PostReadyEffectSnapshot, ...]


class AgentCanvasPostReadyCheckpointRepository:
    """Read one execution and all linked post-Ready effects atomically."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

    def get(self, workflow_id: str, execution_id: str) -> PostReadyExecutionSnapshot:
        try:
            with self._database.engine.connect() as connection:
                with connection.begin():
                    rows = (
                        connection.execute(
                            select(
                                AgentCanvasExecutionRow.workflow_id,
                                AgentCanvasExecutionRow.execution_id,
                                AgentCanvasExecutionRow.status.label("execution_status"),
                                AgentCanvasExecutionRow.updated_at.label("execution_updated_at"),
                                AgentCanvasPostReadyEffectRow.effect_id,
                                AgentCanvasPostReadyEffectRow.effect_type,
                                AgentCanvasPostReadyEffectRow.node_id,
                                AgentCanvasPostReadyEffectRow.status.label("effect_status"),
                                AgentCanvasPostReadyEffectRow.attempt_no,
                                AgentCanvasPostReadyEffectRow.error_json,
                                AgentCanvasPostReadyEffectRow.updated_at.label("effect_updated_at"),
                            )
                            .outerjoin(
                                AgentCanvasExecutionResultCommitRow,
                                AgentCanvasExecutionResultCommitRow.execution_id
                                == AgentCanvasExecutionRow.execution_id,
                            )
                            .outerjoin(
                                AgentCanvasPostReadyEffectRow,
                                AgentCanvasPostReadyEffectRow.source_commit_id
                                == AgentCanvasExecutionResultCommitRow.commit_id,
                            )
                            .where(AgentCanvasExecutionRow.execution_id == execution_id)
                            .order_by(AgentCanvasPostReadyEffectRow.effect_id.asc())
                        )
                        .mappings()
                        .all()
                    )
        except SQLAlchemyError as error:
            raise _error(
                "post_ready_checkpoint_unavailable",
                "Post-Ready checkpoint storage is unavailable.",
            ) from error
        if not rows:
            raise _error("execution_not_found", "Execution was not found.")
        actual_workflow_id = str(rows[0]["workflow_id"])
        if actual_workflow_id != workflow_id:
            raise V2PersistenceError(
                "execution_workflow_mismatch",
                "Execution does not belong to the requested Workflow.",
                stage="agent_canvas_post_ready_checkpoint_repository",
                details={"workflow_id": workflow_id, "execution_id": execution_id},
            )
        effects: list[PostReadyEffectSnapshot] = []
        for row in rows:
            if row["effect_id"] is None:
                continue
            error_json = row["error_json"]
            effects.append(
                PostReadyEffectSnapshot(
                    effect_id=str(row["effect_id"]),
                    effect_type=cast(PostReadyEffectTypeV2, row["effect_type"]),
                    node_id=str(row["node_id"]),
                    status=cast(PostReadyEffectStatusV2, row["effect_status"]),
                    attempt_no=int(row["attempt_no"]),
                    error=(
                        CanvasNodeErrorV2.model_validate(json.loads(str(error_json)))
                        if error_json
                        else None
                    ),
                    updated_at=datetime.fromisoformat(str(row["effect_updated_at"])),
                )
            )
        return PostReadyExecutionSnapshot(
            workflow_id=actual_workflow_id,
            execution_id=str(rows[0]["execution_id"]),
            execution_status=cast(CanvasExecutionStatusV2, rows[0]["execution_status"]),
            updated_at=datetime.fromisoformat(str(rows[0]["execution_updated_at"])),
            effects=tuple(effects),
        )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(
        code,
        message,
        stage="agent_canvas_post_ready_checkpoint_repository",
    )
