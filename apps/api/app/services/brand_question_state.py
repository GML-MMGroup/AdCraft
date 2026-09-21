"""Context-bound card reuse and SQLite writer fencing for Brand intake."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.models import BrandDecisionLogRow, BrandJourneyRow
from app.schemas.brand_professional_mode import BrandOptionCardV1
from app.services.brand_question_context import BrandQuestionContext, BrandQuestionContextService


def stale_context() -> V2PersistenceError:
    return V2PersistenceError(
        "brand_context_stale",
        "The Brand brief has changed. Refresh the current question.",
        stage="brand_question_state",
    )


class BrandQuestionState:
    def __init__(self, database: V2Database) -> None:
        self._database = database
        self._repository = BrandDecisionRepository(database)
        self.context = BrandQuestionContextService(database)

    def claim(self, connection: Connection, brand_id: str, revision: int) -> None:
        """Acquire SQLite write authority before reading publication preconditions."""
        result = connection.execute(
            update(BrandJourneyRow)
            .where(BrandJourneyRow.brand_id == brand_id, BrandJourneyRow.stage_revision == revision)
            .values(stage_revision=BrandJourneyRow.stage_revision)
        )
        if result.rowcount != 1:
            raise stale_context()

    def require_snapshot(
        self, connection: Connection, brand_id: str, snapshot: BrandQuestionContext
    ) -> None:
        if self.context.read_in_transaction(connection, brand_id).digest != snapshot.digest:
            raise stale_context()

    def card_is_current(
        self, connection: Connection, brand_id: str, card: BrandOptionCardV1
    ) -> bool:
        snapshot = self.context.read_in_transaction(connection, brand_id)
        journey = snapshot.payload["journey"]
        if (
            journey is None
            or journey["stage"] != card.stage
            or journey["stage_revision"] != card.stage_revision
        ):
            return False
        row = connection.execute(
            select(BrandDecisionLogRow.detail_json)
            .where(
                BrandDecisionLogRow.brand_id == brand_id,
                BrandDecisionLogRow.target_id == card.card_id,
                BrandDecisionLogRow.target_type == "option_card",
                BrandDecisionLogRow.action == "recommend",
            )
            .order_by(BrandDecisionLogRow.created_at.desc(), BrandDecisionLogRow.log_id.desc())
            .limit(1)
        ).scalar_one_or_none()
        digest = json.loads(row).get("context_digest") if row else None
        if digest is not None:
            return digest == snapshot.digest
        # Untouched non-intake legacy cards keep their existing selection policy.
        return (
            card.stage not in {"brand-memory", "campaign"} or not snapshot.payload["user_sources"]
        )

    def current_card(self, brand_id: str) -> BrandOptionCardV1 | None:
        with self._database.engine.connect() as connection:
            card = self._repository.get_open_card_in_transaction(connection, brand_id)
            return card if card and self.card_is_current(connection, brand_id, card) else None

    def sources_normalized(self, brand_id: str, snapshot: BrandQuestionContext) -> bool:
        if not snapshot.payload["user_sources"] and not snapshot.payload["requirements"]:
            return True
        with self._database.engine.connect() as connection:
            rows = connection.execute(
                select(BrandDecisionLogRow.detail_json)
                .where(
                    BrandDecisionLogRow.brand_id == brand_id,
                    BrandDecisionLogRow.target_type == "option_card",
                    BrandDecisionLogRow.action == "recommend",
                )
                .order_by(BrandDecisionLogRow.created_at.desc(), BrandDecisionLogRow.log_id.desc())
                .limit(32)
            ).scalars()
            return any(
                json.loads(row).get("normalized_input_digest") == snapshot.input_digest
                for row in rows
            )

    def delegated_slots(self, connection: Connection, brand_id: str) -> frozenset[tuple[str, str]]:
        values = {
            (value.stage, value.slot_id): value
            for value in self._repository.get_slot_values_in_transaction(connection, brand_id)
        }
        rows = connection.execute(
            select(BrandDecisionLogRow.stage, BrandDecisionLogRow.detail_json).where(
                BrandDecisionLogRow.brand_id == brand_id,
                BrandDecisionLogRow.action == "select",
                BrandDecisionLogRow.target_type == "option",
            )
        )
        delegated: set[tuple[str, str]] = set()
        for stage, raw in rows:
            detail: dict[str, Any] = json.loads(raw)
            key = (stage, str(detail.get("slot_id", "")))
            value = values.get(key)
            if (
                detail.get("delegated")
                and value is not None
                and value.provenance == "agent_recommended"
                and value.value == detail.get("value")
            ):
                delegated.add(key)
        return frozenset(delegated)
