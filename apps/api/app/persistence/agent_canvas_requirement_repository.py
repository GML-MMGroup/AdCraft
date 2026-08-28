"""Immutable SQLite persistence for Agent Canvas Requirement Ledgers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.models import (
    AgentCanvasRequirementLedgerRevisionRow,
    AgentCanvasRequirementLedgerRow,
)
from app.schemas.agent_canvas_requirements import (
    RequirementLedgerRevisionV1,
    RequirementLedgerV1,
    RequirementRevisionSourceKindV1,
)
from app.services.agent_canvas_character_occurrence_authority import (
    CharacterOccurrenceAuthorityError,
    validate_character_occurrence_authority,
)


_MAX_LEDGER_BYTES = 524_288


class AgentCanvasRequirementRepository:
    """Read and append canonical full-snapshot Requirement Ledger revisions."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

    @property
    def database(self) -> V2Database:
        return self._database

    def initialize_in_transaction(
        self,
        connection: Connection,
        *,
        workflow_id: str,
        created_at: str,
    ) -> RequirementLedgerRevisionV1:
        ledger = RequirementLedgerV1()
        ledger_json, digest = canonical_requirement_ledger(ledger)
        revision_id = f"reqrev_{uuid4().hex}"
        connection.execute(
            insert(AgentCanvasRequirementLedgerRevisionRow).values(
                revision_id=revision_id,
                workflow_id=workflow_id,
                revision_no=1,
                parent_revision_id=None,
                source_kind="initialization",
                source_turn_id=None,
                source_proposal_id=None,
                source_bundle_id=None,
                source_node_id=None,
                ledger_json=ledger_json,
                content_digest=digest,
                created_at=created_at,
            )
        )
        connection.execute(
            insert(AgentCanvasRequirementLedgerRow).values(
                workflow_id=workflow_id,
                current_revision_id=revision_id,
                current_revision_no=1,
                updated_at=created_at,
            )
        )
        return RequirementLedgerRevisionV1(
            workflow_id=workflow_id,
            revision_id=revision_id,
            revision_no=1,
            source_kind="initialization",
            digest=digest,
            ledger=ledger,
            updated_at=created_at,
        )

    def get_current(self, workflow_id: str) -> RequirementLedgerRevisionV1:
        try:
            with self._database.engine.connect() as connection:
                row = _current_row(connection, workflow_id)
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        if row is None:
            raise _not_found_error()
        return _revision_from_row(row)

    def get_current_in_transaction(
        self,
        connection: Connection,
        workflow_id: str,
    ) -> RequirementLedgerRevisionV1:
        """Load the current revision through a caller-owned transaction."""

        row = _current_row(connection, workflow_id)
        if row is None:
            raise _not_found_error()
        return _revision_from_row(row)

    def append_in_transaction(
        self,
        connection: Connection,
        *,
        workflow_id: str,
        expected_revision_no: int,
        next_ledger: RequirementLedgerV1,
        source_kind: RequirementRevisionSourceKindV1,
        created_at: str | datetime,
        source_turn_id: str | None = None,
        source_proposal_id: str | None = None,
        source_bundle_id: str | None = None,
        source_node_id: str | None = None,
    ) -> RequirementLedgerRevisionV1:
        current_row = _current_row(connection, workflow_id)
        if current_row is None:
            raise _not_found_error()
        current = _revision_from_row(current_row)
        if current.revision_no != expected_revision_no:
            raise _revision_conflict_error()

        ledger_json, digest = canonical_requirement_ledger(next_ledger)
        if digest == current.digest:
            return current

        next_revision_no = current.revision_no + 1
        revision_id = f"reqrev_{uuid4().hex}"
        timestamp = created_at.isoformat() if isinstance(created_at, datetime) else created_at
        connection.execute(
            insert(AgentCanvasRequirementLedgerRevisionRow).values(
                revision_id=revision_id,
                workflow_id=workflow_id,
                revision_no=next_revision_no,
                parent_revision_id=current.revision_id,
                source_kind=source_kind,
                source_turn_id=source_turn_id,
                source_proposal_id=source_proposal_id,
                source_bundle_id=source_bundle_id,
                source_node_id=source_node_id,
                ledger_json=ledger_json,
                content_digest=digest,
                created_at=timestamp,
            )
        )
        changed = connection.execute(
            update(AgentCanvasRequirementLedgerRow)
            .where(
                AgentCanvasRequirementLedgerRow.workflow_id == workflow_id,
                AgentCanvasRequirementLedgerRow.current_revision_no == expected_revision_no,
            )
            .values(
                current_revision_id=revision_id,
                current_revision_no=next_revision_no,
                updated_at=timestamp,
            )
        )
        if changed.rowcount != 1:
            raise _revision_conflict_error()
        return RequirementLedgerRevisionV1(
            workflow_id=workflow_id,
            revision_id=revision_id,
            revision_no=next_revision_no,
            parent_revision_id=current.revision_id,
            source_kind=source_kind,
            source_turn_id=source_turn_id,
            source_proposal_id=source_proposal_id,
            source_bundle_id=source_bundle_id,
            source_node_id=source_node_id,
            digest=digest,
            ledger=next_ledger,
            updated_at=timestamp,
        )


def canonical_requirement_ledger(ledger: RequirementLedgerV1) -> tuple[str, str]:
    """Serialize and hash one Ledger using the canonical persistence encoding."""

    try:
        validate_character_occurrence_authority(ledger)
    except CharacterOccurrenceAuthorityError as error:
        raise V2PersistenceError(
            error.code,
            str(error),
            stage="agent_canvas_requirement_repository",
            details=error.details,
        ) from error
    payload = json.dumps(
        ledger.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    if len(payload.encode("utf-8")) > _MAX_LEDGER_BYTES:
        raise V2PersistenceError(
            "requirement_patch_invalid",
            "The Requirement Ledger exceeds the canonical size limit.",
            stage="agent_canvas_requirement_repository",
        )
    return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _current_row(connection: Connection, workflow_id: str) -> RowMapping | None:
    return (
        connection.execute(
            select(
                AgentCanvasRequirementLedgerRevisionRow,
            )
            .join(
                AgentCanvasRequirementLedgerRow,
                AgentCanvasRequirementLedgerRow.current_revision_id
                == AgentCanvasRequirementLedgerRevisionRow.revision_id,
            )
            .where(
                AgentCanvasRequirementLedgerRow.workflow_id == workflow_id,
                AgentCanvasRequirementLedgerRevisionRow.workflow_id == workflow_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def _revision_from_row(row: RowMapping) -> RequirementLedgerRevisionV1:
    ledger_json = str(row["ledger_json"])
    digest = hashlib.sha256(ledger_json.encode("utf-8")).hexdigest()
    if digest != row["content_digest"]:
        raise V2PersistenceError(
            "requirement_persistence_failed",
            "The Requirement Ledger digest does not match its stored snapshot.",
            stage="agent_canvas_requirement_repository",
        )
    try:
        ledger = RequirementLedgerV1.model_validate_json(ledger_json)
    except ValidationError as error:
        messages = " ".join(str(item.get("msg", "")) for item in error.errors())
        if "Character" in messages or "reserved labels" in messages:
            raise V2PersistenceError(
                "character_occurrence_cardinality_mismatch",
                "Persisted Character count, presence, and occurrence authority do not match.",
                stage="agent_canvas_requirement_repository",
                details={"reason": "invalid_persisted_authority", "retryable": False},
            ) from error
        raise V2PersistenceError(
            "requirement_persistence_failed",
            "The persisted Requirement Ledger is invalid.",
            stage="agent_canvas_requirement_repository",
        ) from error
    return RequirementLedgerRevisionV1(
        workflow_id=row["workflow_id"],
        revision_id=row["revision_id"],
        revision_no=row["revision_no"],
        parent_revision_id=row["parent_revision_id"],
        source_kind=row["source_kind"],
        source_turn_id=row["source_turn_id"],
        source_proposal_id=row["source_proposal_id"],
        source_bundle_id=row["source_bundle_id"],
        source_node_id=row["source_node_id"],
        digest=digest,
        ledger=ledger,
        updated_at=row["created_at"],
    )


def _not_found_error() -> V2PersistenceError:
    return V2PersistenceError(
        "requirement_ledger_not_found",
        "The workflow Requirement Ledger was not found.",
        stage="agent_canvas_requirement_repository",
    )


def _revision_conflict_error() -> V2PersistenceError:
    return V2PersistenceError(
        "requirement_revision_conflict",
        "The Requirement Ledger revision is stale.",
        stage="agent_canvas_requirement_repository",
    )


def _persistence_error() -> V2PersistenceError:
    return V2PersistenceError(
        "requirement_persistence_failed",
        "Requirement Ledger persistence failed.",
        stage="agent_canvas_requirement_repository",
    )
