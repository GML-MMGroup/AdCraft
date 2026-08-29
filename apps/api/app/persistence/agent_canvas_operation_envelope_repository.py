"""Immutable persistence for accepted Agent Canvas operation envelopes."""

from __future__ import annotations

import json
from typing import TypeAlias

from pydantic import TypeAdapter
from sqlalchemy import insert, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.models import AgentCanvasOperationEnvelopeRow
from app.schemas.agent_canvas_capabilities import (
    CapabilityCommandEnvelopeV2,
    NextActionEnvelopeV1,
)
from app.schemas.agent_canvas_materialization import (
    CapabilityMaterializationEnvelopeV1,
    ProposalPublicationEnvelopeV1,
)
from app.schemas.agent_canvas_continuation import ContinuationOperationV2
from app.services.agent_canvas_storyboard_selection_identity import (
    validate_storyboard_envelope_identity,
)


OperationEnvelopeV1: TypeAlias = (
    CapabilityCommandEnvelopeV2
    | NextActionEnvelopeV1
    | CapabilityMaterializationEnvelopeV1
    | ProposalPublicationEnvelopeV1
)
_ENVELOPE_ADAPTER = TypeAdapter(OperationEnvelopeV1)


class AgentCanvasOperationEnvelopeRepository:
    """Store accepted capability commands as immutable canonical facts."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

    def create_in_transaction(
        self,
        connection: Connection,
        envelope: OperationEnvelopeV1,
    ) -> OperationEnvelopeV1:
        _validate_storyboard_envelope(envelope)
        canonical = _canonical_json(envelope)
        existing = connection.execute(
            select(AgentCanvasOperationEnvelopeRow).where(
                AgentCanvasOperationEnvelopeRow.envelope_id == envelope.envelope_id
            )
        ).mappings().one_or_none()
        if existing is not None:
            persisted = _persisted_envelope(existing)
            if str(existing["envelope_json"]) != canonical:
                raise _error(
                    "idempotency_conflict",
                    "Operation envelope identity was reused with different content.",
                )
            return persisted
        try:
            connection.execute(
                insert(AgentCanvasOperationEnvelopeRow).values(
                    envelope_id=envelope.envelope_id,
                    turn_id=(
                        envelope.capability_turn_id
                        if isinstance(envelope, CapabilityCommandEnvelopeV2)
                        else (
                            envelope.next_action_turn_id
                            if isinstance(envelope, NextActionEnvelopeV1)
                            else envelope.action_turn_id
                        )
                    ),
                    workflow_id=envelope.workflow_id,
                    envelope_json=canonical,
                    created_at=envelope.created_at.isoformat(),
                )
            )
        except IntegrityError as error:
            raise _error(
                "idempotency_conflict",
                "Operation envelope identity conflicts with persisted state.",
            ) from error
        return envelope

    def get(self, envelope_id: str) -> OperationEnvelopeV1:
        try:
            with self._database.engine.connect() as connection:
                payload = connection.execute(
                    select(AgentCanvasOperationEnvelopeRow).where(
                        AgentCanvasOperationEnvelopeRow.envelope_id == envelope_id
                    )
                ).mappings().one_or_none()
        except SQLAlchemyError as error:
            raise _error(
                "operation_envelope_persistence_failed",
                "Operation envelope could not be loaded.",
            ) from error
        if payload is None:
            raise _error(
                "operation_envelope_not_found",
                "Operation envelope was not found.",
            )
        return _persisted_envelope(payload)

    def get_in_transaction(
        self,
        connection: Connection,
        envelope_id: str,
    ) -> OperationEnvelopeV1:
        payload = connection.execute(
            select(AgentCanvasOperationEnvelopeRow).where(
                AgentCanvasOperationEnvelopeRow.envelope_id == envelope_id
            )
        ).mappings().one_or_none()
        if payload is None:
            raise _error(
                "operation_envelope_not_found",
                "Operation envelope was not found.",
            )
        return _persisted_envelope(payload)

    def validate_identity_in_transaction(
        self,
        connection: Connection,
        *,
        envelope_id: str,
        workflow_id: str,
        operation: ContinuationOperationV2,
        continuation_turn_id: str,
    ) -> OperationEnvelopeV1:
        """Validate one immutable envelope through the caller's transaction."""

        envelope = self.get_in_transaction(connection, envelope_id)
        expected_operation, expected_turn_id = _operation_identity(envelope)
        if (
            envelope.workflow_id != workflow_id
            or expected_operation != operation
            or expected_turn_id != continuation_turn_id
        ):
            raise _error(
                "operation_envelope_identity_invalid",
                "Operation envelope does not match its continuation identity.",
            )
        _validate_storyboard_envelope(envelope)
        return envelope


def _canonical_json(envelope: OperationEnvelopeV1) -> str:
    return json.dumps(
        envelope.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _persisted_envelope(row) -> OperationEnvelopeV1:
    """Decode an envelope row and verify its relational identity columns."""

    try:
        envelope = _ENVELOPE_ADAPTER.validate_json(
            row["envelope_json"],
            context={"allow_retired_historical_envelope": True},
        )
        _validate_storyboard_envelope(envelope)
        _expected_operation, expected_turn_id = _operation_identity(envelope)
    except V2PersistenceError:
        raise
    except (TypeError, ValueError) as error:
        raise _error(
            "operation_envelope_identity_invalid",
            "Persisted operation envelope is malformed.",
        ) from error
    if (
        str(row["envelope_id"]) != envelope.envelope_id
        or str(row["workflow_id"]) != envelope.workflow_id
        or str(row["turn_id"]) != expected_turn_id
    ):
        raise _error(
            "operation_envelope_identity_invalid",
            "Persisted operation envelope linkage does not match its payload.",
        )
    return envelope


def _operation_identity(
    envelope: OperationEnvelopeV1,
) -> tuple[ContinuationOperationV2, str]:
    if isinstance(envelope, NextActionEnvelopeV1):
        return "next_action", envelope.next_action_turn_id
    if isinstance(envelope, CapabilityCommandEnvelopeV2):
        return "capability_command", envelope.capability_turn_id
    return "capability_materialization", envelope.action_turn_id


def _validate_storyboard_envelope(envelope: OperationEnvelopeV1) -> None:
    """Fence server-derived Storyboard identities before any worker use.

    Legacy Storyboard envelopes without the private marker remain readable for
    historical diagnostics.  Once a marker is present, however, it is an
    immutable authority claim and must agree with every digest-derived ID.
    """

    capability_id = getattr(envelope, "capability_id", None)
    markers = tuple(
        marker
        for marker in (
            getattr(envelope, "agent_request_identity", None),
            getattr(envelope, "idempotency_identity", None),
        )
        if isinstance(marker, str) and marker.startswith("storyboard-selection:")
    )
    if not markers:
        return
    if capability_id != "storyboard_design" or len(set(markers)) != 1:
        raise _error(
            "operation_envelope_identity_invalid",
            "Storyboard selection identity is attached to an incompatible envelope.",
        )
    marker = markers[0]
    # Envelopes written before this focused authority used the existing
    # capability/publication identity namespaces.  They remain readable as
    # historical records.  Only the new server-owned namespace opts into the
    # stricter digest/ID fence; malformed values in that namespace fail closed.
    if not isinstance(marker, str) or not marker.startswith("storyboard-selection:"):
        return
    try:
        if validate_storyboard_envelope_identity(envelope) is None:
            raise ValueError("Storyboard operation envelope identity marker is malformed.")
    except (TypeError, ValueError) as error:
        raise _error(
            "operation_envelope_identity_invalid",
            "Storyboard operation envelope identity does not match its payload.",
        ) from error


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="operation_envelope_repository")
