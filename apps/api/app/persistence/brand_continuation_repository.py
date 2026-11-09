"""Fenced delivery of accepted Brand decisions, using the persisted journey as authority."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import Connection

from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.database import V2Database
from app.persistence.models import (
    BrandContinuationRow as Work,
    BrandJourneyRow,
    BrandRow,
    AgentCanvasWorkflowRow,
)


# Detail and next-card operations each have a 480s hard deadline. Expiry is
# longer than both combined, so a live model operation cannot be stolen.
LEASE_SECONDS = 1200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BrandContinuationRepository:
    def __init__(self, database: V2Database) -> None:
        self.database = database
        self.brands = BrandDecisionRepository(database)

    @staticmethod
    def enqueue_in_transaction(
        connection: Connection, *, brand_id: str, workflow_id: str, revision: int
    ) -> str:
        existing = connection.execute(
            select(Work.work_id)
            .where(
                Work.brand_id == brand_id,
                Work.current_revision == revision,
                Work.status.in_(("queued", "running", "failed")),
            )
            .limit(1)
        ).scalar_one_or_none()
        if existing:
            return existing
        work_id = f"brand:{brand_id}:{revision}"
        now = _now()
        connection.execute(
            insert(Work)
            .values(
                work_id=work_id,
                brand_id=brand_id,
                workflow_id=workflow_id,
                source_revision=revision,
                current_revision=revision,
                status="queued",
                attempt_count=0,
                recovery_count=0,
                lease_until=0,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["work_id"])
        )
        return work_id

    @classmethod
    def enqueue_for_workflow_in_transaction(
        cls, connection: Connection, workflow_id: str
    ) -> str | None:
        row = connection.execute(
            select(BrandJourneyRow.brand_id, BrandJourneyRow.stage_revision)
            .join(BrandRow, BrandRow.brand_id == BrandJourneyRow.brand_id)
            .join(AgentCanvasWorkflowRow, AgentCanvasWorkflowRow.project_id == BrandRow.project_id)
            .where(
                AgentCanvasWorkflowRow.workflow_id == workflow_id,
                BrandJourneyRow.stage != "production",
            )
        ).first()
        if row is None:
            return None
        return cls.enqueue_in_transaction(
            connection,
            brand_id=row.brand_id,
            workflow_id=workflow_id,
            revision=row.stage_revision,
        )

    def ensure_current(self, workflow_id: str) -> str | None:
        project_id = self.brands.project_id_for_workflow(workflow_id)
        brand_id = self.brands.get_brand_id_by_project(project_id) if project_id else None
        if brand_id is None:
            return None
        with self.database.engine.begin() as connection:
            # Serialize admission against concurrent choices before reading revision.
            connection.execute(
                update(BrandJourneyRow)
                .where(BrandJourneyRow.brand_id == brand_id)
                .values(stage_revision=BrandJourneyRow.stage_revision)
            )
            journey = self.brands.get_journey_in_transaction(connection, brand_id)
            if journey is None or journey.stage == "production":
                return None
            return self.enqueue_in_transaction(
                connection,
                brand_id=brand_id,
                workflow_id=workflow_id,
                revision=journey.stage_revision,
            )

    @staticmethod
    def checkpoint_in_transaction(
        connection: Connection, brand_id: str, previous_revision: int, next_revision: int
    ) -> None:
        connection.execute(
            update(Work)
            .where(
                Work.brand_id == brand_id,
                Work.current_revision == previous_revision,
                Work.status.in_(("queued", "running")),
            )
            .values(current_revision=next_revision, updated_at=_now())
        )

    def current(self, brand_id: str, revision: int) -> dict[str, Any] | None:
        with self.database.engine.connect() as connection:
            row = (
                connection.execute(
                    select(Work)
                    .where(
                        Work.brand_id == brand_id,
                        Work.current_revision == revision,
                        Work.status.in_(("queued", "running", "failed")),
                    )
                    .order_by(Work.created_at.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )
            return dict(row) if row else None

    def get(self, work_id: str) -> dict[str, Any]:
        with self.database.engine.connect() as connection:
            return dict(
                connection.execute(select(Work).where(Work.work_id == work_id)).mappings().one()
            )

    def due(self) -> tuple[str, ...]:
        with self.database.engine.connect() as connection:
            return tuple(
                connection.execute(
                    select(Work.work_id)
                    .where(
                        or_(
                            Work.status == "queued",
                            (Work.status == "running") & (Work.lease_until <= int(time.time())),
                        )
                    )
                    .order_by(Work.created_at)
                    .limit(8)
                ).scalars()
            )

    def claim(self, work_id: str, *, retry_failed: bool = False) -> dict[str, Any] | None:
        now = int(time.time())
        with self.database.engine.begin() as connection:
            # Take the writer fence before checking owner, revision and expiry.
            connection.execute(
                update(Work).where(Work.work_id == work_id).values(attempt_count=Work.attempt_count)
            )
            row = connection.execute(select(Work).where(Work.work_id == work_id)).mappings().one()
            journey = self.brands.get_journey_in_transaction(connection, row["brand_id"])
            if (
                journey is None
                or journey.stage == "production"
                or journey.stage_revision != row["current_revision"]
            ):
                connection.execute(
                    update(Work)
                    .where(Work.work_id == work_id)
                    .values(status="superseded", lease_until=0, updated_at=_now())
                )
                return None
            if row["status"] in {"completed", "superseded"}:
                return None
            if row["status"] == "failed" and not retry_failed:
                return None
            if row["status"] == "running" and row["lease_until"] > now:
                return None
            abandoned = row["status"] == "running"
            if abandoned and row["recovery_count"] >= 1:
                connection.execute(
                    update(Work)
                    .where(Work.work_id == work_id)
                    .values(
                        status="failed",
                        error_code="brand_continuation_interrupted",
                        lease_until=0,
                        updated_at=_now(),
                    )
                )
                return None
            token = uuid4().hex
            values = dict(
                status="running",
                attempt_count=row["attempt_count"] + 1,
                recovery_count=row["recovery_count"] + int(abandoned) if not retry_failed else 0,
                lease_token=token,
                lease_until=now + LEASE_SECONDS,
                error_code=None,
                updated_at=_now(),
            )
            connection.execute(update(Work).where(Work.work_id == work_id).values(**values))
            return {**dict(row), **values}

    def finish(self, claim: dict[str, Any], *, error_code: str | None = None) -> bool:
        with self.database.engine.begin() as connection:
            result = connection.execute(
                update(Work)
                .where(
                    Work.work_id == claim["work_id"],
                    Work.status == "running",
                    Work.lease_token == claim["lease_token"],
                    Work.lease_until > int(time.time()),
                )
                .values(
                    status="failed" if error_code else "completed",
                    lease_until=0,
                    error_code=error_code,
                    updated_at=_now(),
                )
            )
            return result.rowcount == 1
