"""Bounded, read-only product context projected from existing SQLite authority."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.database import V2Database
from app.persistence.models import (
    AgentCanvasChatEntryRow,
    AgentCanvasRequirementLedgerRevisionRow,
    AgentCanvasRequirementLedgerRow,
    BrandDecisionLogRow,
)


@dataclass(frozen=True)
class BrandQuestionContext:
    workflow_id: str | None
    payload: dict[str, Any]

    @property
    def digest(self) -> str:
        return sha256(
            json.dumps(self.payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()

    @property
    def input_digest(self) -> str:
        return sha256(
            json.dumps(
                [self.payload["user_sources"], self.payload["requirements"]],
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()


class BrandQuestionContextService:
    def __init__(self, database: V2Database) -> None:
        self._database = database
        self._repository = BrandDecisionRepository(database)

    def read(self, brand_id: str) -> BrandQuestionContext:
        with self._database.engine.connect() as connection:
            return self.read_in_transaction(connection, brand_id)

    def read_in_transaction(self, connection: Connection, brand_id: str) -> BrandQuestionContext:
        workflow_id = self._repository.workflow_id_for_brand(brand_id)
        values = self._repository.get_slot_values_in_transaction(connection, brand_id)
        journey = self._repository.get_journey_in_transaction(connection, brand_id)
        sources = self._user_sources(connection, workflow_id) if workflow_id else []
        custom = connection.execute(
            select(BrandDecisionLogRow)
            .where(
                BrandDecisionLogRow.brand_id == brand_id,
                BrandDecisionLogRow.target_type == "custom_answer",
            )
            .order_by(BrandDecisionLogRow.created_at.desc(), BrandDecisionLogRow.log_id)
            .limit(16)
        ).mappings()
        for row in custom:
            detail = json.loads(row["detail_json"])
            sources.append(
                {
                    "source_id": row["log_id"],
                    "text": str(detail["text"])[:4096],
                    "created_at": row["created_at"],
                    "target_slot_id": detail.get("slot_id"),
                    "content_digest": sha256(str(detail["text"]).encode()).hexdigest(),
                }
            )
        sources.sort(key=lambda source: (source["created_at"], source["source_id"]))
        ledger = (
            connection.execute(
                select(AgentCanvasRequirementLedgerRevisionRow)
                .join(
                    AgentCanvasRequirementLedgerRow,
                    AgentCanvasRequirementLedgerRow.current_revision_id
                    == AgentCanvasRequirementLedgerRevisionRow.revision_id,
                )
                .where(AgentCanvasRequirementLedgerRow.workflow_id == workflow_id)
            )
            .mappings()
            .first()
            if workflow_id
            else None
        )
        requirement_context: dict[str, Any] = {}
        if ledger is not None:
            content = json.loads(ledger["ledger_json"])
            requirement_context = {
                "revision_id": ledger["revision_id"],
                "content_digest": ledger["content_digest"],
                "hard_controls": content.get("hard_controls", []),
                "active_directives": content.get("active_directives", [])[-32:],
                "unresolved_conflicts": content.get("unresolved_conflicts", [])[:16],
            }
        return BrandQuestionContext(
            workflow_id=workflow_id,
            payload={
                "schema_version": "1",
                "user_sources": sources,
                "requirements": requirement_context,
                "confirmed_values": [
                    value.model_dump(mode="json")
                    for value in values
                    if value.provenance == "user_confirmed"
                ],
                "assumptions": [
                    value.model_dump(mode="json")
                    for value in values
                    if value.provenance == "agent_recommended"
                ],
                "journey": journey.model_dump(mode="json") if journey else None,
            },
        )

    def _user_sources(self, connection: Connection, workflow_id: str) -> list[dict[str, Any]]:
        query = select(AgentCanvasChatEntryRow).where(
            AgentCanvasChatEntryRow.workflow_id == workflow_id,
            AgentCanvasChatEntryRow.entry_type == "message",
            AgentCanvasChatEntryRow.speaker == "user",
        )
        recent = list(
            connection.execute(
                query.order_by(AgentCanvasChatEntryRow.sequence_no.desc()).limit(16)
            ).mappings()
        )
        # Retain the opening production request even after long conversations.
        production = connection.execute(
            select(AgentCanvasChatEntryRow.metadata_json)
            .where(
                AgentCanvasChatEntryRow.workflow_id == workflow_id,
                func.json_extract(AgentCanvasChatEntryRow.metadata_json, "$.intent_mode")
                == "guided_production",
            )
            .order_by(AgentCanvasChatEntryRow.sequence_no)
            .limit(1)
        ).scalar_one_or_none()
        turn_id = json.loads(production).get("turn_id") if production else None
        first = (
            connection.execute(
                query.where(
                    func.json_extract(AgentCanvasChatEntryRow.metadata_json, "$.turn_id") == turn_id
                )
                .order_by(AgentCanvasChatEntryRow.sequence_no)
                .limit(1)
                if turn_id
                else query.order_by(AgentCanvasChatEntryRow.sequence_no).limit(1)
            )
            .mappings()
            .first()
        )
        rows = {row["entry_id"]: row for row in recent}
        if first is not None:
            rows[first["entry_id"]] = first
        return [
            {
                "source_id": json.loads(row["metadata_json"]).get("turn_id", row["entry_id"]),
                "text": row["content"][:4096],
                "created_at": row["created_at"],
                "content_digest": sha256(row["content"].encode()).hexdigest(),
            }
            for row in sorted(rows.values(), key=lambda row: row["sequence_no"])
        ]
