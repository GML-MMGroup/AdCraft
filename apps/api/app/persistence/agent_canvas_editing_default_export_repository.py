"""Durable scheduling receipts for automatic default Editing delivery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json

from sqlalchemy import func, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.dialects.sqlite import insert

from app.persistence.database import V2Database
from app.persistence.models import (
    AgentCanvasEditingDefaultExportRow as Job,
    AgentCanvasEditingExportRow as Export,
    AgentCanvasNodeRow as Node,
    AgentCanvasWorkflowRow as Workflow,
    ProjectRow,
)
from app.schemas.agent_canvas import CanvasPositionV2

DEFAULT_EXPORT_INTENT = "automatic_default_export"


@dataclass(frozen=True)
class DefaultEditingExport:
    node_id: str
    workflow_id: str
    status: str
    export_id: str | None
    output_node_id: str | None
    position: CanvasPositionV2
    error_code: str | None

    @property
    def idempotency_key(self) -> str:
        return f"editing-default-export-v1:{self.node_id}"


def _record(row: RowMapping) -> DefaultEditingExport:
    return DefaultEditingExport(
        node_id=row["node_id"],
        workflow_id=row["workflow_id"],
        status=row["status"],
        export_id=row["export_id"],
        output_node_id=row["output_node_id"],
        position=CanvasPositionV2.model_validate_json(row["position_json"]),
        error_code=row["error_code"],
    )


class EditingDefaultExportRepository:
    def __init__(self, database: V2Database) -> None:
        self.database = database

    def discover(self, *, limit: int = 32) -> None:
        """Creation metadata is durable intent; historical nodes are never enrolled."""
        now = datetime.now(timezone.utc).isoformat()
        with self.database.engine.begin() as connection:
            candidates = (
                connection.execute(
                    select(Node.node_id, Node.workflow_id, Node.position_x, Node.position_y)
                    .join(Workflow, Workflow.workflow_id == Node.workflow_id)
                    .join(ProjectRow, ProjectRow.project_id == Workflow.project_id)
                    .outerjoin(Job, Job.node_id == Node.node_id)
                    .where(
                        Node.node_type == "editing",
                        func.json_extract(Node.metadata_json, "$._deleted_at").is_(None),
                        ProjectRow.status == "active",
                        Job.node_id.is_(None),
                        func.json_extract(Node.metadata_json, "$." + DEFAULT_EXPORT_INTENT) == 1,
                    )
                    .order_by(Node.created_at, Node.node_id)
                    .limit(limit)
                )
                .mappings()
                .all()
            )
            for row in candidates:
                connection.execute(
                    insert(Job)
                    .values(
                        node_id=row["node_id"],
                        workflow_id=row["workflow_id"],
                        status="waiting",
                        position_json=json.dumps(
                            {"x": row["position_x"] + 400, "y": row["position_y"]}
                        ),
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["node_id"])
                )

    def pending(self, *, limit: int = 16) -> tuple[DefaultEditingExport, ...]:
        with self.database.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(Job)
                    .join(Node, Node.node_id == Job.node_id)
                    .where(func.json_extract(Node.metadata_json, "$._deleted_at").is_(None))
                    .join(Workflow, Workflow.workflow_id == Job.workflow_id)
                    .join(ProjectRow, ProjectRow.project_id == Workflow.project_id)
                    .where(Job.status.in_(("waiting", "exporting")), ProjectRow.status == "active")
                    .order_by(Job.updated_at, Job.node_id)
                    .limit(limit)
                )
                .mappings()
                .all()
            )
            return tuple(_record(row) for row in rows)

    def get(self, node_id: str) -> DefaultEditingExport | None:
        with self.database.engine.connect() as connection:
            row = (
                connection.execute(select(Job).where(Job.node_id == node_id))
                .mappings()
                .one_or_none()
            )
            return _record(row) if row else None

    def accepted_export(self, job: DefaultEditingExport) -> str | None:
        """Recover the gap between export admission and recording its identity here."""
        with self.database.engine.connect() as connection:
            return connection.execute(
                select(Export.export_id).where(
                    Export.workflow_id == job.workflow_id,
                    Export.node_id == job.node_id,
                    Export.idempotency_key == job.idempotency_key,
                )
            ).scalar_one_or_none()

    def record(
        self,
        job: DefaultEditingExport,
        *,
        status: str,
        export_id: str | None = None,
        output_node_id: str | None = None,
        error_code: str | None = None,
    ) -> None:
        values = dict(
            status=status, error_code=error_code, updated_at=datetime.now(timezone.utc).isoformat()
        )
        if export_id is not None:
            values["export_id"] = export_id
        if output_node_id is not None:
            values["output_node_id"] = output_node_id
        allowed = (
            ("waiting",)
            if status in {"waiting", "skipped"} and job.export_id is None
            else ("waiting", "exporting")
        )
        with self.database.engine.begin() as connection:
            connection.execute(
                update(Job)
                .where(Job.node_id == job.node_id, Job.status.in_(allowed))
                .values(**values)
            )
