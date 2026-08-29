"""Durable dispatch ownership for V2 Node prompt preparation.

The repository deliberately mirrors the existing fenced outbox primitives,
but keeps Node preparation separate from conversation continuation.  All
mutations use a short SQLite transaction and all work that may invoke an
Agent is performed by the worker after the lease is committed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
import json
from hashlib import sha256
from typing import Any

from sqlalchemy import and_, insert, or_, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasBindingRow,
    AgentCanvasNodeRow,
    AgentCanvasPromptPreparationOutboxRow,
    AssetVersionRow,
    ProviderModelRow,
    AgentCanvasWorkflowRow,
)
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_errors import CanvasNodeErrorV2
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1
from app.schemas.agent_canvas_prompt_preparation_dispatch import (
    PromptPreparationDispatchV1,
    detached_context_payload,
    prompt_preparation_dispatch_id,
    prompt_preparation_dispatch_logical_key,
)
from app.schemas.v2_persistence import V2EventInsert


APPLICABLE_NODE_TYPES = frozenset({"text", "script", "image", "video", "audio"})
NON_TERMINAL_STATUSES = ("queued", "leased")


class AgentCanvasPromptPreparationDispatchRepository:
    """Own durable prompt-preparation identities and renewable leases."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Prompt dispatch and events must share one V2Database.")
        self._database = database
        self._events = events

    @property
    def database(self) -> V2Database:
        return self._database

    def enqueue(
        self,
        dispatch: PromptPreparationDispatchV1 | None = None,
        *,
        now: datetime | None = None,
        **fields: object,
    ) -> PromptPreparationDispatchV1:
        """Insert one dispatch, returning an exact replay for duplicate identity."""

        candidate = _coerce_dispatch(dispatch, fields, now=now)
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    result = self.enqueue_in_transaction(connection, candidate)
                    connection.commit()
                    return result
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _error(
                "prompt_preparation_dispatch_identity_conflict",
                "Prompt-preparation dispatch identity conflicts with an existing record.",
            ) from error
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def enqueue_in_transaction(
        self,
        connection: Connection,
        dispatch: PromptPreparationDispatchV1 | None = None,
        *,
        now: datetime | None = None,
        emit_event: bool = True,
        **fields: object,
    ) -> PromptPreparationDispatchV1:
        """Insert/replay a dispatch in a caller-owned transaction."""

        candidate = _coerce_dispatch(dispatch, fields, now=now)
        if candidate.status not in {
            "queued",
            "completed",
            "failed",
            "superseded",
        }:
            raise _error(
                "prompt_preparation_dispatch_invalid",
                "Prompt-preparation dispatch state is invalid for enqueue.",
            )
        existing = _select_by_logical_key(connection, candidate.logical_key)
        if existing is not None:
            _require_same_identity(existing, candidate)
            return _dispatch_from_row(existing)
        operation_row = (
            connection.execute(
                select(AgentCanvasPromptPreparationOutboxRow).where(
                    AgentCanvasPromptPreparationOutboxRow.workflow_id == candidate.workflow_id,
                    AgentCanvasPromptPreparationOutboxRow.node_id == candidate.node_id,
                    AgentCanvasPromptPreparationOutboxRow.operation_id == candidate.operation_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if operation_row is not None:
            raise _error(
                "prompt_preparation_dispatch_identity_conflict",
                "Operation identity is already bound to a different input snapshot.",
            )
        values = _dispatch_values(candidate)
        try:
            connection.execute(insert(AgentCanvasPromptPreparationOutboxRow).values(**values))
        except IntegrityError as error:
            replay = _select_by_logical_key(connection, candidate.logical_key)
            if replay is not None:
                _require_same_identity(replay, candidate)
                return _dispatch_from_row(replay)
            raise _error(
                "prompt_preparation_dispatch_identity_conflict",
                "Prompt-preparation dispatch identity conflicts with an existing record.",
            ) from error
        if emit_event:
            self._append_event(
                connection,
                candidate,
                event_type={
                    "queued": "node_prompt_preparation_queued",
                    "completed": "node_prompt_preparation_dispatch_reconciled",
                    "failed": "node_prompt_preparation_dispatch_reconciled",
                    "superseded": "node_prompt_preparation_superseded",
                }[candidate.status],
                transition_key=f"prompt-dispatch:{candidate.dispatch_id}:{candidate.status}",
                created_at=candidate.created_at,
            )
        return candidate

    def ensure_for_node(
        self,
        node: CanvasNodeV2,
        *,
        bindings: Sequence[object] = (),
        context: Mapping[str, object] | None = None,
        now: datetime | None = None,
    ) -> PromptPreparationDispatchV1 | None:
        """Ensure one dispatch for a current Node outside a larger transaction."""

        timestamp = _utc(now or datetime.now(timezone.utc))
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    result = self.ensure_for_node_in_transaction(
                        connection,
                        node,
                        bindings=bindings,
                        context=context,
                        now=timestamp,
                    )
                    connection.commit()
                    return result
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    # Keep the authority discoverable under the name used by the workflow and
    # materialization callers.  These wrappers intentionally delegate to the
    # one implementation above; there is no second dispatch state machine.
    def ensure_prompt_preparation_dispatch(
        self,
        node: CanvasNodeV2,
        *,
        bindings: Sequence[object] = (),
        context: Mapping[str, object] | None = None,
        now: datetime | None = None,
    ) -> PromptPreparationDispatchV1 | None:
        return self.ensure_for_node(node, bindings=bindings, context=context, now=now)

    def ensure_prompt_preparation_dispatch_in_transaction(
        self,
        connection: Connection,
        node: CanvasNodeV2,
        *,
        bindings: Sequence[object] = (),
        context: Mapping[str, object] | None = None,
        now: datetime | None = None,
    ) -> PromptPreparationDispatchV1 | None:
        return self.ensure_for_node_in_transaction(
            connection,
            node,
            bindings=bindings,
            context=context,
            now=now,
        )

    def ensure_for_node_in_transaction(
        self,
        connection: Connection,
        node: CanvasNodeV2,
        *,
        bindings: Sequence[object] = (),
        context: Mapping[str, object] | None = None,
        now: datetime | None = None,
        emit_event: bool = True,
    ) -> PromptPreparationDispatchV1 | None:
        """Ensure the current queued projection has one matching dispatch.

        Source-only and explicit ``not_applicable`` projections are intentionally
        no-ops.  A queued generative projection always receives a deterministic
        operation identity before its row is inserted.
        """

        if not _is_trackable_node(node):
            return None
        timestamp = _utc(now or datetime.now(timezone.utc))
        context_json, context_digest = _detached_context(context)
        normalized = normalize_queued_node(
            node,
            bindings=bindings,
            context_digest=context_digest if context is not None else None,
        )
        preparation = normalized.prompt_preparation
        if preparation.status == "working":
            # A legacy working projection has no durable owner that can be
            # safely reconstructed. Leave it untouched for recovery code to
            # report explicitly rather than inventing a lease owner.
            return None
        if preparation.status not in {"queued", "ready", "failed", "superseded"}:
            return None
        if not preparation.operation_id and preparation.status != "queued":
            # Manually authored Ready content has no preparation operation and
            # therefore no dispatch lineage to own.
            return None
        if not preparation.operation_id:
            raise _error(
                "prompt_preparation_dispatch_missing",
                "Applicable queued preparation has no operation identity.",
            )
        _assert_node_projection(connection, normalized)
        source_snapshot = _source_snapshot_for_node(connection, normalized, bindings)
        logical_key = prompt_preparation_dispatch_logical_key(
            workflow_id=normalized.workflow_id,
            node_id=normalized.node_id,
            node_revision=normalized.revision,
            operation_id=preparation.operation_id,
            role_variant=preparation.role_variant,
            occurrence_id=preparation.occurrence_id,
            character_phase=preparation.character_phase,
            context_snapshot_id=preparation.context_snapshot_id,
            context_digest=context_digest,
            binding_digest=preparation.binding_digest,
            recipe_digest=preparation.recipe_digest,
            style_projection_digest=preparation.style_projection_digest,
            brief_digest=preparation.brief_digest,
            requirement_revision_id=preparation.requirement_revision_id,
            requirement_revision_no=preparation.requirement_revision_no,
            document_revisions=preparation.document_revisions,
            source_snapshot=source_snapshot,
            model_policy_revision=_model_policy_revision(normalized),
        )
        dispatch_status = {
            "queued": "queued",
            "ready": "completed",
            "failed": "failed",
            "superseded": "superseded",
        }[preparation.status]
        terminal_at = (
            timestamp if dispatch_status in {"completed", "failed", "superseded"} else None
        )
        dispatch = PromptPreparationDispatchV1(
            dispatch_id=prompt_preparation_dispatch_id(logical_key),
            workflow_id=normalized.workflow_id,
            node_id=normalized.node_id,
            node_revision=normalized.revision,
            operation_id=preparation.operation_id,
            logical_key=logical_key,
            role_variant=preparation.role_variant,
            occurrence_id=preparation.occurrence_id,
            character_phase=preparation.character_phase,
            context_snapshot_id=preparation.context_snapshot_id,
            context_digest=context_digest,
            context_json=context_json,
            binding_digest=preparation.binding_digest,
            recipe_digest=preparation.recipe_digest,
            style_projection_digest=preparation.style_projection_digest,
            brief_digest=preparation.brief_digest,
            requirement_revision_id=preparation.requirement_revision_id,
            requirement_revision_no=preparation.requirement_revision_no,
            document_revisions=dict(preparation.document_revisions),
            source_snapshot=source_snapshot,
            model_policy_revision=_model_policy_revision(normalized),
            status=dispatch_status,
            attempt_no=preparation.attempt_no,
            max_attempts=5,
            available_at=timestamp,
            last_error_code=(preparation.error.code if preparation.error is not None else None),
            last_error_message=(
                "Node prompt preparation failed." if preparation.error is not None else None
            ),
            supersession_reason=(
                "legacy_node_prompt_preparation_superseded"
                if dispatch_status == "superseded"
                else None
            ),
            created_at=timestamp,
            updated_at=timestamp,
            terminal_at=terminal_at,
        )
        return self.enqueue_in_transaction(connection, dispatch, emit_event=emit_event)

    def get(self, dispatch_id: str) -> PromptPreparationDispatchV1:
        try:
            with self._database.engine.connect() as connection:
                row = _select_one(connection, dispatch_id)
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        if row is None:
            raise _error(
                "prompt_preparation_dispatch_not_found",
                "Prompt-preparation dispatch was not found.",
            )
        return _dispatch_from_row(row)

    def get_by_logical_key(self, logical_key: str) -> PromptPreparationDispatchV1 | None:
        try:
            with self._database.engine.connect() as connection:
                row = _select_by_logical_key(connection, logical_key)
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return _dispatch_from_row(row) if row is not None else None

    def get_by_node_operation(
        self,
        workflow_id: str,
        node_id: str,
        operation_id: str,
    ) -> PromptPreparationDispatchV1 | None:
        """Load the dispatch that owns one exact Node preparation operation.

        Recovery must not select a merely "current" row by revision or creation
        order: a committed materialization carries the operation identity as
        its durable join key.  If legacy data contains more than one row for
        that key, fail closed instead of guessing which immutable context to
        restore.
        """

        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasPromptPreparationOutboxRow).where(
                            AgentCanvasPromptPreparationOutboxRow.workflow_id == workflow_id,
                            AgentCanvasPromptPreparationOutboxRow.node_id == node_id,
                            AgentCanvasPromptPreparationOutboxRow.operation_id == operation_id,
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        if len(rows) > 1:
            raise _error(
                "prompt_preparation_dispatch_ambiguous",
                "Multiple prompt-preparation dispatches own the same operation.",
            )
        return _dispatch_from_row(rows[0]) if rows else None

    # Keep the exact-operation lookup discoverable under the recovery-facing
    # name while retaining one implementation and one authority.
    def get_for_node_operation(
        self,
        workflow_id: str,
        node_id: str,
        operation_id: str,
    ) -> PromptPreparationDispatchV1 | None:
        return self.get_by_node_operation(workflow_id, node_id, operation_id)

    def get_current_for_node(
        self,
        workflow_id: str,
        node_id: str,
    ) -> PromptPreparationDispatchV1 | None:
        """Resolve the dispatch owned by the Node's persisted operation.

        Dispatch history is intentionally retained for audit and retry
        analysis, so a Node may have several terminal or superseded rows over
        its lifetime.  The current Node projection is the join authority: a
        persisted operation identity selects exactly one row.  Only legacy
        rows without a persisted operation use the conservative ambiguity
        check, which fails closed instead of guessing by insertion order.
        """
        try:
            with self._database.engine.connect() as connection:
                node_preparation = connection.execute(
                    select(AgentCanvasNodeRow.prompt_preparation_json).where(
                        AgentCanvasNodeRow.workflow_id == workflow_id,
                        AgentCanvasNodeRow.node_id == node_id,
                    )
                ).scalar_one_or_none()
                operation_id = _parse_json_object(node_preparation).get("operation_id")
                query = select(AgentCanvasPromptPreparationOutboxRow).where(
                    AgentCanvasPromptPreparationOutboxRow.workflow_id == workflow_id,
                    AgentCanvasPromptPreparationOutboxRow.node_id == node_id,
                )
                if isinstance(operation_id, str) and operation_id:
                    # Exact operation identity is the only safe current-row
                    # selector once a Node projection has been persisted.
                    query = query.where(
                        AgentCanvasPromptPreparationOutboxRow.operation_id == operation_id
                    )
                else:
                    # Legacy/malformed rows have no join key.  Restrict the
                    # fallback to live/terminal candidates and fail closed if
                    # more than one identity remains.
                    query = query.where(
                        AgentCanvasPromptPreparationOutboxRow.status.in_(
                            (*NON_TERMINAL_STATUSES, "completed", "failed")
                        )
                    ).order_by(
                        AgentCanvasPromptPreparationOutboxRow.node_revision.desc(),
                        AgentCanvasPromptPreparationOutboxRow.created_at.desc(),
                        AgentCanvasPromptPreparationOutboxRow.dispatch_id.desc(),
                    )
                rows = connection.execute(query).mappings().all()
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        if len(rows) > 1:
            raise _error(
                "prompt_preparation_dispatch_ambiguous",
                "Multiple current prompt-preparation dispatches exist for the Node.",
            )
        row = rows[0] if rows else None
        return _dispatch_from_row(row) if row is not None else None

    def list_for_workflow(self, workflow_id: str) -> tuple[PromptPreparationDispatchV1, ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasPromptPreparationOutboxRow)
                        .where(AgentCanvasPromptPreparationOutboxRow.workflow_id == workflow_id)
                        .order_by(
                            AgentCanvasPromptPreparationOutboxRow.created_at.asc(),
                            AgentCanvasPromptPreparationOutboxRow.dispatch_id.asc(),
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return tuple(_dispatch_from_row(row) for row in rows)

    def list_nonterminal_for_workflow(
        self,
        workflow_id: str,
    ) -> tuple[PromptPreparationDispatchV1, ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasPromptPreparationOutboxRow)
                        .where(
                            AgentCanvasPromptPreparationOutboxRow.workflow_id == workflow_id,
                            AgentCanvasPromptPreparationOutboxRow.status.in_(NON_TERMINAL_STATUSES),
                        )
                        .order_by(
                            AgentCanvasPromptPreparationOutboxRow.available_at.asc(),
                            AgentCanvasPromptPreparationOutboxRow.created_at.asc(),
                            AgentCanvasPromptPreparationOutboxRow.dispatch_id.asc(),
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return tuple(_dispatch_from_row(row) for row in rows)

    def claim_due(
        self,
        *,
        worker_id: str,
        now: datetime,
        batch_limit: int = 8,
        lease_duration: timedelta = timedelta(seconds=60),
        _terminalized_out: list[PromptPreparationDispatchV1] | None = None,
    ) -> tuple[PromptPreparationDispatchV1, ...]:
        timestamp = _utc(now)
        if not worker_id or batch_limit < 1 or lease_duration <= timedelta(0):
            raise _error(
                "prompt_preparation_dispatch_claim_invalid",
                "Prompt-preparation claim settings are invalid.",
            )
        now_value = _iso(timestamp)
        expiry_value = _iso(timestamp + lease_duration)
        terminalized: list[PromptPreparationDispatchV1] = []
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    due = or_(
                        and_(
                            AgentCanvasPromptPreparationOutboxRow.status == "queued",
                            AgentCanvasPromptPreparationOutboxRow.available_at <= now_value,
                        ),
                        and_(
                            AgentCanvasPromptPreparationOutboxRow.status == "leased",
                            AgentCanvasPromptPreparationOutboxRow.lease_expires_at <= now_value,
                        ),
                    )
                    # Select runnable and exhausted rows independently.  An
                    # exhausted row is still terminalized in this transaction,
                    # but it must not consume the bounded claim capacity for a
                    # later runnable row.
                    runnable_rows = list(
                        connection.execute(
                            select(AgentCanvasPromptPreparationOutboxRow)
                            .where(
                                due,
                                AgentCanvasPromptPreparationOutboxRow.attempt_count
                                < AgentCanvasPromptPreparationOutboxRow.max_attempts,
                            )
                            .order_by(
                                AgentCanvasPromptPreparationOutboxRow.available_at.asc(),
                                AgentCanvasPromptPreparationOutboxRow.created_at.asc(),
                                AgentCanvasPromptPreparationOutboxRow.dispatch_id.asc(),
                            )
                            .limit(batch_limit)
                        ).mappings()
                    )
                    exhausted_rows = list(
                        connection.execute(
                            select(AgentCanvasPromptPreparationOutboxRow)
                            .where(
                                due,
                                AgentCanvasPromptPreparationOutboxRow.attempt_count
                                >= AgentCanvasPromptPreparationOutboxRow.max_attempts,
                            )
                            .order_by(
                                AgentCanvasPromptPreparationOutboxRow.available_at.asc(),
                                AgentCanvasPromptPreparationOutboxRow.created_at.asc(),
                                AgentCanvasPromptPreparationOutboxRow.dispatch_id.asc(),
                            )
                            .limit(batch_limit)
                        ).mappings()
                    )
                    rows = [*exhausted_rows, *runnable_rows]
                    claimed: list[PromptPreparationDispatchV1] = []
                    for row in rows:
                        current_attempt = int(row["attempt_count"])
                        if current_attempt >= int(row["max_attempts"]):
                            failed_at = _iso(timestamp)
                            changed = connection.execute(
                                update(AgentCanvasPromptPreparationOutboxRow)
                                .where(
                                    AgentCanvasPromptPreparationOutboxRow.dispatch_id
                                    == row["dispatch_id"],
                                    AgentCanvasPromptPreparationOutboxRow.status == row["status"],
                                    AgentCanvasPromptPreparationOutboxRow.lease_generation
                                    == row["lease_generation"],
                                )
                                .values(
                                    status="failed",
                                    lease_owner=None,
                                    lease_expires_at=None,
                                    last_error_code="prompt_preparation_retry_exhausted",
                                    last_error_message="Prompt preparation retry budget was exhausted.",
                                    updated_at=failed_at,
                                    terminal_at=failed_at,
                                )
                            )
                            if changed.rowcount == 1:
                                failed_row = {
                                    **row,
                                    "status": "failed",
                                    "lease_owner": None,
                                    "lease_expires_at": None,
                                    "last_error_code": "prompt_preparation_retry_exhausted",
                                    "last_error_message": "Prompt preparation retry budget was exhausted.",
                                    "updated_at": failed_at,
                                    "terminal_at": failed_at,
                                }
                                projected = self._project_terminal_failure_in_transaction(
                                    connection,
                                    failed_row,
                                    error_code="prompt_preparation_retry_exhausted",
                                    error_message="Prompt preparation retry budget was exhausted.",
                                    now=timestamp,
                                )
                                self._append_event(
                                    connection,
                                    _dispatch_from_row(failed_row),
                                    event_type=(
                                        "node_prompt_preparation_dispatch_reconciled"
                                        if projected
                                        else "node_prompt_preparation_failed"
                                    ),
                                    transition_key=(
                                        f"prompt-dispatch:{row['dispatch_id']}:retry-exhausted"
                                    ),
                                    created_at=timestamp,
                                )
                                terminalized.append(_dispatch_from_row(failed_row))
                            continue
                        generation = int(row["lease_generation"]) + 1
                        changed = connection.execute(
                            update(AgentCanvasPromptPreparationOutboxRow)
                            .where(
                                AgentCanvasPromptPreparationOutboxRow.dispatch_id
                                == row["dispatch_id"],
                                AgentCanvasPromptPreparationOutboxRow.status == row["status"],
                                AgentCanvasPromptPreparationOutboxRow.lease_generation
                                == row["lease_generation"],
                            )
                            .values(
                                status="leased",
                                attempt_count=current_attempt + 1,
                                lease_owner=worker_id,
                                lease_generation=generation,
                                lease_expires_at=expiry_value,
                                updated_at=now_value,
                            )
                        )
                        if changed.rowcount != 1:
                            continue
                        updated = {
                            **row,
                            "status": "leased",
                            "attempt_count": current_attempt + 1,
                            "lease_owner": worker_id,
                            "lease_generation": generation,
                            "lease_expires_at": expiry_value,
                            "updated_at": now_value,
                        }
                        dispatch = _dispatch_from_row(updated)
                        self._append_event(
                            connection,
                            dispatch,
                            event_type="node_prompt_preparation_started",
                            transition_key=(
                                f"prompt-dispatch:{dispatch.dispatch_id}:started:{generation}"
                            ),
                            created_at=timestamp,
                        )
                        claimed.append(dispatch)
                    connection.commit()
                    if _terminalized_out is not None:
                        _terminalized_out.extend(terminalized)
                    return tuple(claimed)
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def claim_due_with_terminalized(
        self,
        *,
        worker_id: str,
        now: datetime,
        batch_limit: int = 8,
        lease_duration: timedelta = timedelta(seconds=60),
    ) -> tuple[
        tuple[PromptPreparationDispatchV1, ...],
        tuple[PromptPreparationDispatchV1, ...],
    ]:
        """Claim runnable rows and return rows terminalized by retry exhaustion.

        Exhausted rows are deliberately excluded from the claimed capacity, but
        their committed terminal transition still needs to reach the existing
        barrier callback.  Returning both sets keeps that notification outside
        the SQLite transaction while preserving the original ``claim_due`` API.
        """

        terminalized: list[PromptPreparationDispatchV1] = []
        claimed = self.claim_due(
            worker_id=worker_id,
            now=now,
            batch_limit=batch_limit,
            lease_duration=lease_duration,
            _terminalized_out=terminalized,
        )
        return claimed, tuple(terminalized)

    def renew_lease(
        self,
        dispatch_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        now: datetime,
        lease_duration: timedelta = timedelta(seconds=60),
    ) -> PromptPreparationDispatchV1:
        timestamp = _utc(now)
        if lease_duration <= timedelta(0):
            raise _error(
                "prompt_preparation_dispatch_claim_invalid",
                "Prompt-preparation lease duration must be positive.",
            )
        try:
            with self._database.engine.begin() as connection:
                row = _select_one(connection, dispatch_id)
                if row is None:
                    raise _not_found()
                _require_owned(row, worker_id, lease_generation, timestamp)
                expires = _iso(timestamp + lease_duration)
                changed = connection.execute(
                    update(AgentCanvasPromptPreparationOutboxRow)
                    .where(
                        AgentCanvasPromptPreparationOutboxRow.dispatch_id == dispatch_id,
                        AgentCanvasPromptPreparationOutboxRow.status == "leased",
                        AgentCanvasPromptPreparationOutboxRow.lease_owner == worker_id,
                        AgentCanvasPromptPreparationOutboxRow.lease_generation == lease_generation,
                    )
                    .values(lease_expires_at=expires, updated_at=_iso(timestamp))
                )
                if changed.rowcount != 1:
                    raise _stale_lease()
                return _dispatch_from_row(
                    {**row, "lease_expires_at": expires, "updated_at": _iso(timestamp)}
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def assert_owned(
        self,
        dispatch_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        now: datetime,
    ) -> None:
        dispatch = self.get(dispatch_id)
        if (
            dispatch.status != "leased"
            or dispatch.lease_owner != worker_id
            or dispatch.lease_generation != lease_generation
            or dispatch.lease_expires_at is None
            or dispatch.lease_expires_at <= _utc(now)
        ):
            raise _stale_lease()

    def assert_current_snapshot(
        self,
        dispatch: PromptPreparationDispatchV1,
        *,
        now: datetime,
    ) -> None:
        """Fence a claimed dispatch against the current persisted Node inputs.

        The Node revision advances when preparation moves through ``working``
        and ``ready``.  Those lifecycle revisions are therefore deliberately
        not compared as a literal value here.  The immutable operation,
        occurrence metadata, and dependency/source snapshot are the authority
        that decides whether a worker may continue.
        """

        timestamp = _utc(now)
        try:
            with self._database.engine.connect() as connection:
                row = _select_one(connection, dispatch.dispatch_id)
                if row is None:
                    raise _not_found()
                if row["status"] != "leased":
                    raise _stale_dispatch()
                if row["lease_expires_at"] is None:
                    raise _stale_dispatch()
                if _datetime(row["lease_expires_at"]) <= timestamp:
                    raise _stale_lease()
                _assert_current_node_identity(
                    connection,
                    row,
                    node_revision=None,
                    operation_id=dispatch.operation_id,
                    context_digest=dispatch.context_digest,
                    source_snapshot=dispatch.source_snapshot,
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def supersede_owned_fenced(
        self,
        dispatch_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        reason: str,
        now: datetime,
    ) -> PromptPreparationDispatchV1:
        """Supersede a stale leased row with an ownership CAS.

        A callback that loses its lease is not permitted to mutate the row.  If
        another transaction already reconciled it, returning that terminal row
        is an idempotent no-op; otherwise only the exact owner/generation may
        publish the superseded disposition.
        """

        timestamp = _utc(now)
        try:
            with self._database.engine.begin() as connection:
                row = _select_one(connection, dispatch_id)
                if row is None:
                    raise _not_found()
                if row["status"] == "superseded":
                    return _dispatch_from_row(row)
                _require_owned(row, worker_id, lease_generation, timestamp)
                values = {
                    "status": "superseded",
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error_code": "prompt_preparation_superseded",
                    "last_error_message": _bounded(reason, 1_024),
                    "supersession_reason": _bounded(reason, 1_024),
                    "updated_at": _iso(timestamp),
                    "terminal_at": _iso(timestamp),
                }
                changed = connection.execute(
                    update(AgentCanvasPromptPreparationOutboxRow)
                    .where(
                        AgentCanvasPromptPreparationOutboxRow.dispatch_id == dispatch_id,
                        AgentCanvasPromptPreparationOutboxRow.status == "leased",
                        AgentCanvasPromptPreparationOutboxRow.lease_owner == worker_id,
                        AgentCanvasPromptPreparationOutboxRow.lease_generation == lease_generation,
                    )
                    .values(**values)
                )
                if changed.rowcount != 1:
                    raise _stale_lease()
                updated = {**row, **values}
                result = _dispatch_from_row(updated)
                self._append_event(
                    connection,
                    result,
                    event_type="node_prompt_preparation_superseded",
                    transition_key=(f"prompt-dispatch:{dispatch_id}:superseded:{lease_generation}"),
                    created_at=timestamp,
                )
                return result
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def requeue_failed(
        self,
        dispatch_id: str,
        *,
        next_attempt_at: datetime,
        error_code: str,
        error_message: str,
        now: datetime,
        node_revision: int | None = None,
        operation_id: str | None = None,
        context_digest: str | None = None,
        source_snapshot: Mapping[str, object] | None = None,
    ) -> PromptPreparationDispatchV1:
        """Reopen a retryable terminal row without changing its identity."""

        timestamp = _utc(now)
        available = _utc(next_attempt_at)
        if available < timestamp:
            raise _error(
                "prompt_preparation_dispatch_retry_invalid",
                "Retry time cannot precede the current time.",
            )
        try:
            with self._database.engine.begin() as connection:
                row = _select_one(connection, dispatch_id)
                if row is None:
                    raise _not_found()
                if (
                    node_revision is not None
                    or operation_id is not None
                    or context_digest is not None
                    or source_snapshot is not None
                ):
                    _assert_current_node_identity(
                        connection,
                        row,
                        node_revision=node_revision,
                        operation_id=operation_id,
                        context_digest=context_digest,
                        source_snapshot=source_snapshot,
                    )
                if row["status"] == "queued":
                    return _dispatch_from_row(row)
                if row["status"] != "failed":
                    raise _error(
                        "prompt_preparation_dispatch_state_conflict",
                        "Only a failed prompt-preparation dispatch can be retried.",
                    )
                if int(row["attempt_count"]) >= int(row["max_attempts"]):
                    raise _error(
                        "prompt_preparation_dispatch_retry_exhausted",
                        "Prompt-preparation retry budget was exhausted.",
                    )
                values = {
                    "status": "queued",
                    "available_at": _iso(available),
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error_code": _bounded(error_code, 160),
                    "last_error_message": _bounded(error_message, 1_024),
                    "updated_at": _iso(timestamp),
                    "terminal_at": None,
                }
                changed = connection.execute(
                    update(AgentCanvasPromptPreparationOutboxRow)
                    .where(
                        AgentCanvasPromptPreparationOutboxRow.dispatch_id == dispatch_id,
                        AgentCanvasPromptPreparationOutboxRow.status == "failed",
                    )
                    .values(**values)
                )
                if changed.rowcount != 1:
                    raise _error(
                        "prompt_preparation_dispatch_state_conflict",
                        "Prompt-preparation dispatch changed before retry.",
                    )
                result = _dispatch_from_row({**row, **values})
                self._append_event(
                    connection,
                    result,
                    event_type="node_prompt_preparation_queued",
                    transition_key=f"prompt-dispatch:{dispatch_id}:retry:{result.attempt_no}",
                    created_at=timestamp,
                )
                return result
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def reconcile_node_terminal_in_transaction(
        self,
        connection: Connection,
        *,
        node: CanvasNodeV2,
        now: datetime,
    ) -> PromptPreparationDispatchV1 | None:
        """Reconcile a Node terminal projection with its durable dispatch.

        This is intentionally a small projection bridge: the Node service
        remains the authoring authority, while this method records the already
        committed terminal outcome for the matching operation.  It never
        creates a provider task or changes the Node itself.
        """

        preparation = node.prompt_preparation
        if preparation.status not in {"ready", "failed", "superseded"}:
            return None
        operation_id = preparation.operation_id
        if not operation_id:
            return None
        row = (
            connection.execute(
                select(AgentCanvasPromptPreparationOutboxRow).where(
                    AgentCanvasPromptPreparationOutboxRow.workflow_id == node.workflow_id,
                    AgentCanvasPromptPreparationOutboxRow.node_id == node.node_id,
                    AgentCanvasPromptPreparationOutboxRow.operation_id == operation_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            # A terminal Node without its exact durable owner has no immutable
            # proof from which a safe dispatch can be reconstructed.  Never
            # synthesize an empty-context terminal row from mutable Node data.
            raise _error(
                "prompt_preparation_dispatch_missing",
                "Terminal prompt preparation has no matching dispatch owner.",
            )
        _assert_terminal_projection_identity(connection, row, node)
        if row["status"] in {"completed", "failed", "superseded"}:
            return _dispatch_from_row(row)
        status = {
            "ready": "completed",
            "failed": "failed",
            "superseded": "superseded",
        }[preparation.status]
        timestamp = _utc(now)
        error_code = preparation.error.code if preparation.error is not None else None
        error_message = "Node prompt preparation failed." if error_code is not None else None
        reason = "node_prompt_preparation_superseded" if status == "superseded" else None
        values = {
            "status": status,
            "lease_owner": None,
            "lease_expires_at": None,
            "last_error_code": error_code or ("prompt_preparation_superseded" if reason else None),
            "last_error_message": error_message or reason,
            "supersession_reason": reason,
            "updated_at": _iso(timestamp),
            "terminal_at": _iso(timestamp),
        }
        changed = connection.execute(
            update(AgentCanvasPromptPreparationOutboxRow)
            .where(
                AgentCanvasPromptPreparationOutboxRow.dispatch_id == row["dispatch_id"],
                AgentCanvasPromptPreparationOutboxRow.status.in_(NON_TERMINAL_STATUSES),
            )
            .values(**values)
        )
        if changed.rowcount != 1:
            latest = _select_one(connection, str(row["dispatch_id"]))
            return _dispatch_from_row(latest) if latest is not None else None
        result = _dispatch_from_row({**row, **values})
        self._append_event(
            connection,
            result,
            event_type=(
                "node_prompt_preparation_superseded"
                if status == "superseded"
                else "node_prompt_preparation_dispatch_reconciled"
            ),
            transition_key=f"prompt-dispatch:{result.dispatch_id}:reconcile:{status}",
            created_at=timestamp,
        )
        return result

    def complete(
        self,
        dispatch_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        now: datetime,
        node_revision: int | None = None,
        operation_id: str | None = None,
        context_digest: str | None = None,
        source_snapshot: Mapping[str, object] | None = None,
    ) -> PromptPreparationDispatchV1:
        return self._finish_owned(
            dispatch_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
            status="completed",
            now=now,
            node_revision=node_revision,
            operation_id=operation_id,
            context_digest=context_digest,
            source_snapshot=source_snapshot,
        )

    def schedule_retry(
        self,
        dispatch_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        next_attempt_at: datetime,
        error_code: str,
        error_message: str,
        now: datetime,
        node_revision: int | None = None,
        operation_id: str | None = None,
        context_digest: str | None = None,
        source_snapshot: Mapping[str, object] | None = None,
    ) -> PromptPreparationDispatchV1:
        timestamp = _utc(now)
        available = _utc(next_attempt_at)
        if available < timestamp:
            raise _error(
                "prompt_preparation_dispatch_retry_invalid",
                "Retry time cannot precede the current time.",
            )
        return self._finish_owned(
            dispatch_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
            status="queued",
            now=timestamp,
            available_at=available,
            error_code=error_code,
            error_message=error_message,
            keep_error=True,
            node_revision=node_revision,
            operation_id=operation_id,
            context_digest=context_digest,
            source_snapshot=source_snapshot,
        )

    def fail(
        self,
        dispatch_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        error_code: str,
        error_message: str,
        now: datetime,
        node_revision: int | None = None,
        operation_id: str | None = None,
        context_digest: str | None = None,
        source_snapshot: Mapping[str, object] | None = None,
    ) -> PromptPreparationDispatchV1:
        return self._finish_owned(
            dispatch_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
            status="failed",
            now=now,
            error_code=error_code,
            error_message=error_message,
            keep_error=True,
            node_revision=node_revision,
            operation_id=operation_id,
            context_digest=context_digest,
            source_snapshot=source_snapshot,
        )

    def supersede(
        self,
        dispatch_id: str,
        *,
        reason: str,
        now: datetime,
        successor_dispatch_id: str | None = None,
    ) -> PromptPreparationDispatchV1:
        timestamp = _utc(now)
        try:
            with self._database.engine.begin() as connection:
                row = _select_one(connection, dispatch_id)
                if row is None:
                    raise _not_found()
                if row["status"] == "superseded":
                    return _dispatch_from_row(row)
                values = {
                    "status": "superseded",
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error_code": "prompt_preparation_superseded",
                    "last_error_message": _bounded(reason, 1_024),
                    "supersession_reason": _bounded(reason, 1_024),
                    "superseded_by_dispatch_id": successor_dispatch_id,
                    "updated_at": _iso(timestamp),
                    "terminal_at": _iso(timestamp),
                }
                changed = connection.execute(
                    update(AgentCanvasPromptPreparationOutboxRow)
                    .where(
                        AgentCanvasPromptPreparationOutboxRow.dispatch_id == dispatch_id,
                        AgentCanvasPromptPreparationOutboxRow.status.in_(
                            (*NON_TERMINAL_STATUSES, "completed", "failed")
                        ),
                    )
                    .values(**values)
                )
                if changed.rowcount != 1:
                    raise _error(
                        "prompt_preparation_dispatch_state_conflict",
                        "Dispatch changed before supersession.",
                    )
                updated = {**row, **values}
                dispatch = _dispatch_from_row(updated)
                self._append_event(
                    connection,
                    dispatch,
                    event_type="node_prompt_preparation_superseded",
                    transition_key=f"prompt-dispatch:{dispatch_id}:superseded:{row['lease_generation']}",
                    created_at=timestamp,
                )
                return dispatch
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def supersede_owned(
        self,
        dispatch_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        reason: str,
        now: datetime,
    ) -> PromptPreparationDispatchV1:
        return self._finish_owned(
            dispatch_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
            status="superseded",
            now=now,
            error_code="prompt_preparation_superseded",
            error_message=reason,
            supersession_reason=reason,
        )

    def supersede_and_enqueue_in_transaction(
        self,
        connection: Connection,
        *,
        node: CanvasNodeV2,
        bindings: Sequence[object] = (),
        context: Mapping[str, object] | None = None,
        reason: str,
        now: datetime,
    ) -> PromptPreparationDispatchV1 | None:
        """Atomically supersede current identities and enqueue one successor."""

        if not _is_applicable_node(node):
            return None
        context_json, context_digest = _detached_context(context)
        normalized = normalize_queued_node(
            node,
            bindings=bindings,
            context_digest=context_digest if context is not None else None,
        )
        source_snapshot = _source_snapshot_for_node(connection, normalized, bindings)
        preparation = normalized.prompt_preparation
        if not preparation.operation_id:
            raise _error(
                "prompt_preparation_dispatch_missing",
                "Successor preparation has no operation identity.",
            )
        logical_key = prompt_preparation_dispatch_logical_key(
            workflow_id=normalized.workflow_id,
            node_id=normalized.node_id,
            node_revision=normalized.revision,
            operation_id=preparation.operation_id,
            role_variant=preparation.role_variant,
            occurrence_id=preparation.occurrence_id,
            character_phase=preparation.character_phase,
            context_snapshot_id=preparation.context_snapshot_id,
            context_digest=context_digest,
            binding_digest=preparation.binding_digest,
            recipe_digest=preparation.recipe_digest,
            style_projection_digest=preparation.style_projection_digest,
            brief_digest=preparation.brief_digest,
            requirement_revision_id=preparation.requirement_revision_id,
            requirement_revision_no=preparation.requirement_revision_no,
            document_revisions=preparation.document_revisions,
            source_snapshot=source_snapshot,
            model_policy_revision=_model_policy_revision(normalized),
        )
        successor = PromptPreparationDispatchV1(
            dispatch_id=prompt_preparation_dispatch_id(logical_key),
            workflow_id=normalized.workflow_id,
            node_id=normalized.node_id,
            node_revision=normalized.revision,
            operation_id=preparation.operation_id,
            logical_key=logical_key,
            role_variant=preparation.role_variant,
            occurrence_id=preparation.occurrence_id,
            character_phase=preparation.character_phase,
            context_snapshot_id=preparation.context_snapshot_id,
            context_digest=context_digest,
            context_json=context_json,
            binding_digest=preparation.binding_digest,
            recipe_digest=preparation.recipe_digest,
            style_projection_digest=preparation.style_projection_digest,
            brief_digest=preparation.brief_digest,
            requirement_revision_id=preparation.requirement_revision_id,
            requirement_revision_no=preparation.requirement_revision_no,
            document_revisions=dict(preparation.document_revisions),
            source_snapshot=source_snapshot,
            model_policy_revision=_model_policy_revision(normalized),
            status="queued",
            attempt_no=0,
            max_attempts=5,
            available_at=_utc(now),
            created_at=_utc(now),
            updated_at=_utc(now),
        )
        active_rows = (
            connection.execute(
                select(AgentCanvasPromptPreparationOutboxRow).where(
                    AgentCanvasPromptPreparationOutboxRow.workflow_id == normalized.workflow_id,
                    AgentCanvasPromptPreparationOutboxRow.node_id == normalized.node_id,
                    AgentCanvasPromptPreparationOutboxRow.status.in_(
                        (*NON_TERMINAL_STATUSES, "completed", "failed")
                    ),
                )
            )
            .mappings()
            .all()
        )
        for row in active_rows:
            if row["logical_key"] == successor.logical_key:
                continue
            changed = connection.execute(
                update(AgentCanvasPromptPreparationOutboxRow)
                .where(
                    AgentCanvasPromptPreparationOutboxRow.dispatch_id == row["dispatch_id"],
                    AgentCanvasPromptPreparationOutboxRow.status.in_(
                        (*NON_TERMINAL_STATUSES, "completed", "failed")
                    ),
                )
                .values(
                    status="superseded",
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code="prompt_preparation_superseded",
                    last_error_message=_bounded(reason, 1_024),
                    supersession_reason=_bounded(reason, 1_024),
                    superseded_by_dispatch_id=successor.dispatch_id,
                    updated_at=_iso(_utc(now)),
                    terminal_at=_iso(_utc(now)),
                )
            )
            if changed.rowcount != 1:
                raise _error(
                    "prompt_preparation_dispatch_state_conflict",
                    "Dispatch changed before supersession.",
                )
            self._append_event(
                connection,
                _dispatch_from_row(
                    {
                        **row,
                        "status": "superseded",
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "last_error_code": "prompt_preparation_superseded",
                        "last_error_message": _bounded(reason, 1_024),
                        "supersession_reason": _bounded(reason, 1_024),
                        "superseded_by_dispatch_id": successor.dispatch_id,
                        "updated_at": _iso(_utc(now)),
                        "terminal_at": _iso(_utc(now)),
                    }
                ),
                event_type="node_prompt_preparation_superseded",
                transition_key=f"prompt-dispatch:{row['dispatch_id']}:superseded:{row['lease_generation']}",
                created_at=_utc(now),
            )
        return self.enqueue_in_transaction(connection, successor)

    def _finish_owned(
        self,
        dispatch_id: str,
        *,
        worker_id: str,
        lease_generation: int,
        status: str,
        now: datetime,
        available_at: datetime | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        keep_error: bool = False,
        supersession_reason: str | None = None,
        node_revision: int | None = None,
        operation_id: str | None = None,
        context_digest: str | None = None,
        source_snapshot: Mapping[str, object] | None = None,
    ) -> PromptPreparationDispatchV1:
        timestamp = _utc(now)
        if status not in {"queued", "completed", "failed", "superseded"}:
            raise _error("prompt_preparation_dispatch_invalid", "Invalid dispatch terminal state.")
        try:
            with self._database.engine.begin() as connection:
                row = _select_one(connection, dispatch_id)
                if row is None:
                    raise _not_found()
                _require_owned(row, worker_id, lease_generation, timestamp)
                if any(
                    value is not None
                    for value in (node_revision, operation_id, context_digest, source_snapshot)
                ):
                    _assert_current_node_identity(
                        connection,
                        row,
                        node_revision=node_revision,
                        operation_id=operation_id,
                        context_digest=context_digest,
                        source_snapshot=source_snapshot,
                    )
                terminal = status in {"completed", "failed", "superseded"}
                values = {
                    "status": status,
                    "available_at": _iso(available_at or timestamp),
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error_code": _bounded(error_code, 160) if keep_error else None,
                    "last_error_message": _bounded(error_message, 1_024) if keep_error else None,
                    "supersession_reason": _bounded(supersession_reason, 1_024),
                    "updated_at": _iso(timestamp),
                    "terminal_at": _iso(timestamp) if terminal else None,
                }
                changed = connection.execute(
                    update(AgentCanvasPromptPreparationOutboxRow)
                    .where(
                        AgentCanvasPromptPreparationOutboxRow.dispatch_id == dispatch_id,
                        AgentCanvasPromptPreparationOutboxRow.status == "leased",
                        AgentCanvasPromptPreparationOutboxRow.lease_owner == worker_id,
                        AgentCanvasPromptPreparationOutboxRow.lease_generation == lease_generation,
                    )
                    .values(**values)
                )
                if changed.rowcount != 1:
                    raise _stale_lease()
                updated = {**row, **values}
                dispatch = _dispatch_from_row(updated)
                projected = False
                if status == "failed":
                    projected = self._project_terminal_failure_in_transaction(
                        connection,
                        updated,
                        error_code=error_code or "prompt_preparation_failed",
                        error_message=error_message or "Prompt preparation failed.",
                        now=timestamp,
                    )
                event_type = {
                    "queued": "node_prompt_preparation_dispatch_reconciled",
                    "completed": "node_prompt_preparation_dispatch_reconciled",
                    "failed": (
                        "node_prompt_preparation_dispatch_reconciled"
                        if projected
                        else "node_prompt_preparation_failed"
                    ),
                    "superseded": "node_prompt_preparation_superseded",
                }[status]
                self._append_event(
                    connection,
                    dispatch,
                    event_type=event_type,
                    transition_key=f"prompt-dispatch:{dispatch_id}:{event_type}:{lease_generation}",
                    created_at=timestamp,
                )
                return dispatch
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def _append_event(
        self,
        connection: Connection,
        dispatch: PromptPreparationDispatchV1,
        *,
        event_type: str,
        transition_key: str,
        created_at: datetime,
    ) -> None:
        self._events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=dispatch.workflow_id,
                node_id=dispatch.node_id,
                event_type=event_type,
                transition_key=transition_key,
                created_at=_iso(created_at),
                payload={
                    "dispatch_id": dispatch.dispatch_id,
                    "node_revision": dispatch.node_revision,
                    "operation_id": dispatch.operation_id,
                    "logical_key": dispatch.logical_key,
                    "status": dispatch.status,
                    "attempt": dispatch.attempt_no,
                    "lease_generation": dispatch.lease_generation,
                    "error_code": dispatch.last_error_code,
                    "occurrence_id": dispatch.occurrence_id,
                    "character_phase": dispatch.character_phase,
                    "source_snapshot_digest": _json_digest(dispatch.source_snapshot),
                },
            ),
        )

    def _project_terminal_failure_in_transaction(
        self,
        connection: Connection,
        dispatch_row: Mapping[str, Any],
        *,
        error_code: str,
        error_message: str,
        now: datetime,
    ) -> bool:
        """Project a dispatch terminal failure onto its managed Node atomically."""

        node_row = (
            connection.execute(
                select(AgentCanvasNodeRow).where(
                    AgentCanvasNodeRow.workflow_id == dispatch_row["workflow_id"],
                    AgentCanvasNodeRow.node_id == dispatch_row["node_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if node_row is None:
            return False
        if (
            str(node_row["node_type"]) not in APPLICABLE_NODE_TYPES
            or str(node_row["execution_mode"]) != "generative"
        ):
            return False
        try:
            preparation = NodePromptPreparationV1.model_validate_json(
                str(node_row["prompt_preparation_json"])
            )
        except (TypeError, ValueError) as error:
            raise _error(
                "prompt_preparation_dispatch_corrupt",
                "Managed Node prompt-preparation projection is invalid.",
            ) from error
        if preparation.operation_id != str(dispatch_row["operation_id"]):
            # A newer operation owns the Node.  Never overwrite its projection.
            return False
        if preparation.status in {"failed", "ready", "superseded", "not_applicable"}:
            return False
        if preparation.status not in {"queued", "working"}:
            return False
        timestamp = _iso(_utc(now))
        failed_preparation = preparation.model_copy(
            update={
                "status": "failed",
                "error": CanvasNodeErrorV2(
                    code=error_code,
                    message=_bounded(error_message, 1_024) or "Prompt preparation failed.",
                    retryable=False,
                ),
                "attempt_stage": "failed",
                "updated_at": _utc(now),
            }
        )
        changed = connection.execute(
            update(AgentCanvasNodeRow)
            .where(
                AgentCanvasNodeRow.workflow_id == dispatch_row["workflow_id"],
                AgentCanvasNodeRow.node_id == dispatch_row["node_id"],
                AgentCanvasNodeRow.revision == node_row["revision"],
            )
            .values(
                prompt_preparation_json=failed_preparation.model_dump_json(),
                revision=int(node_row["revision"]) + 1,
                updated_at=timestamp,
            )
        )
        if changed.rowcount != 1:
            raise _stale_dispatch()
        workflow_revision = connection.execute(
            select(AgentCanvasWorkflowRow.revision).where(
                AgentCanvasWorkflowRow.workflow_id == dispatch_row["workflow_id"]
            )
        ).scalar_one_or_none()
        if workflow_revision is None:
            raise _error(
                "prompt_preparation_dispatch_workflow_missing",
                "Prompt-preparation dispatch workflow was not found.",
            )
        workflow_revision = int(workflow_revision)
        workflow_changed = connection.execute(
            update(AgentCanvasWorkflowRow)
            .where(
                AgentCanvasWorkflowRow.workflow_id == dispatch_row["workflow_id"],
                AgentCanvasWorkflowRow.revision == workflow_revision,
            )
            .values(revision=workflow_revision + 1, updated_at=timestamp)
        )
        if workflow_changed.rowcount != 1:
            raise _stale_dispatch()
        self._events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=str(dispatch_row["workflow_id"]),
                node_id=str(dispatch_row["node_id"]),
                event_type="node_prompt_preparation_failed",
                transition_key=(
                    f"prompt-node:{dispatch_row['node_id']}:{dispatch_row['operation_id']}:failed"
                ),
                created_at=timestamp,
                payload={
                    "node_revision": int(node_row["revision"]) + 1,
                    "workflow_revision": workflow_revision + 1,
                    "prompt_preparation_status": "failed",
                    "operation_id": str(dispatch_row["operation_id"]),
                    "error_code": error_code,
                },
            ),
        )
        return True


# Short aliases used by callers and tests; they intentionally share one class.
PromptPreparationDispatchRepository = AgentCanvasPromptPreparationDispatchRepository
AgentCanvasPromptPreparationOutboxRepository = AgentCanvasPromptPreparationDispatchRepository


def _is_applicable_node(node: CanvasNodeV2) -> bool:
    return (
        node.node_type in APPLICABLE_NODE_TYPES
        and node.execution_mode == "generative"
        and node.prompt_preparation.status == "queued"
    )


def _is_trackable_node(node: CanvasNodeV2) -> bool:
    """Return whether a generative preparation has a durable identity to track."""

    return (
        node.node_type in APPLICABLE_NODE_TYPES
        and node.execution_mode == "generative"
        and node.prompt_preparation.status in {"queued", "ready", "failed", "superseded", "working"}
    )


def normalize_queued_node(
    node: CanvasNodeV2,
    *,
    bindings: Sequence[object] = (),
    context_digest: str | None = None,
) -> CanvasNodeV2:
    """Give a queued Node a stable operation identity without creative inference."""

    preparation = node.prompt_preparation
    if preparation.status != "queued":
        return node
    # A caller that supplies a frozen context is asking the authority to
    # reconcile the operation against that snapshot.  Do not blindly retain an
    # operation generated before the context changed; retries with the same
    # context still derive the same value below and therefore remain idempotent.
    if preparation.operation_id and context_digest is None and not bindings:
        return node
    binding_seed = []
    for item in bindings:
        dumped = _safe_model_dump(item)
        if dumped and dumped.get("enabled", True):
            binding_seed.append(dumped)
    binding_seed.sort(key=_binding_seed_key)
    seed = {
        "workflow_id": node.workflow_id,
        "node_id": node.node_id,
        "node_revision": node.revision,
        "node_type": node.node_type,
        "creative_role": node.creative_role,
        "role_contract_version": node.role_contract_version,
        "execution_mode": node.execution_mode,
        "summary_prompt": node.summary_prompt,
        "generation_prompt": node.generation_prompt,
        "structured_content": node.structured_content,
        "model_selection_mode": node.model_selection_mode,
        "model_ref": node.model_ref,
        "model_policy_revision": _model_policy_revision(node),
        "parameters": node.parameters,
        "parameter_provenance": {
            field: provenance.model_dump(mode="json")
            for field, provenance in node.parameter_provenance.items()
        },
        "prompt_context_snapshot_id": node.prompt_context_snapshot_id,
        "output_asset_id": node.output_asset_id,
        "context_digest": context_digest,
        "metadata": node.metadata,
        "prompt_preparation": {
            "context_snapshot_id": preparation.context_snapshot_id,
            "occurrence_id": preparation.occurrence_id,
            "character_phase": preparation.character_phase,
            "role_variant": preparation.role_variant,
            "recipe_id": preparation.recipe_id,
            "recipe_version": preparation.recipe_version,
            "recipe_digest": preparation.recipe_digest,
            "requirement_revision_id": preparation.requirement_revision_id,
            "requirement_revision_no": preparation.requirement_revision_no,
            "document_revisions": preparation.document_revisions,
            "binding_digest": preparation.binding_digest,
            "style_projection_digest": preparation.style_projection_digest,
            "brief_digest": preparation.brief_digest,
            "prompt_digest": preparation.prompt_digest,
            "parameter_origins": [
                origin.model_dump(mode="json") for origin in preparation.parameter_origins
            ],
            "assertion_evidence": _safe_model_dump(preparation.assertion_evidence),
        },
        "bindings": binding_seed,
    }
    encoded = json.dumps(seed, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    operation_id = "prep_" + sha256(encoded.encode("utf-8")).hexdigest()[:40]
    if preparation.operation_id == operation_id:
        return node
    return node.model_copy(
        update={"prompt_preparation": preparation.model_copy(update={"operation_id": operation_id})}
    )


def _source_snapshot(node: CanvasNodeV2, bindings: Sequence[object]) -> dict[str, object]:
    values: list[dict[str, object]] = []
    for binding in bindings:
        dumped = _safe_model_dump(binding)
        if dumped:
            values.append(dumped)
    return {
        "node_revision": node.revision,
        "output_asset_id": node.output_asset_id,
        "bindings": values,
        "occurrence_id": node.metadata.get("occurrence_id"),
        "character_phase": node.metadata.get("character_phase"),
    }


def _source_snapshot_for_node(
    connection: Connection,
    node: CanvasNodeV2,
    bindings: Sequence[object],
) -> dict[str, object]:
    """Capture the authoritative input lineage for one queued Node.

    Bindings are read from SQLite after the caller has applied its mutation;
    the optional sequence is only a fallback for callers that are constructing
    a node before inserting its bindings.  Source node revisions and pinned
    AssetVersions are included so a later dependency change necessarily yields
    a different dispatch identity.
    """

    rows = (
        connection.execute(
            select(AgentCanvasBindingRow)
            .where(
                AgentCanvasBindingRow.workflow_id == node.workflow_id,
                AgentCanvasBindingRow.target_node_id == node.node_id,
                AgentCanvasBindingRow.enabled.is_(True),
            )
            .order_by(
                AgentCanvasBindingRow.order_index.asc(),
                AgentCanvasBindingRow.binding_id.asc(),
            )
        )
        .mappings()
        .all()
    )
    binding_values: list[dict[str, object]] = []
    if rows:
        for row in rows:
            metadata = _parse_json_object(row["metadata_json"])
            source_node_id = row["source_node_id"]
            source: dict[str, object] | None = None
            if source_node_id:
                source_row = (
                    connection.execute(
                        select(
                            AgentCanvasNodeRow.node_id,
                            AgentCanvasNodeRow.revision,
                            AgentCanvasNodeRow.output_asset_id,
                            AgentCanvasNodeRow.prompt_preparation_json,
                            AgentCanvasNodeRow.metadata_json,
                        ).where(
                            AgentCanvasNodeRow.workflow_id == node.workflow_id,
                            AgentCanvasNodeRow.node_id == source_node_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if source_row is not None:
                    source_preparation = _parse_json_object(source_row["prompt_preparation_json"])
                    source_metadata = _parse_json_object(source_row["metadata_json"])
                    pinned_version = source_metadata.get("source_version_id")
                    if not isinstance(pinned_version, str) or not pinned_version:
                        pinned_version = source_metadata.get("source_asset_version_id")
                    pinned_version = (
                        pinned_version
                        if isinstance(pinned_version, str) and pinned_version
                        else None
                    )
                    version_query = select(
                        AssetVersionRow.version_id,
                        AssetVersionRow.version_no,
                        AssetVersionRow.sha256,
                        AssetVersionRow.status,
                    ).where(AssetVersionRow.asset_id == source_row["output_asset_id"])
                    if pinned_version is not None:
                        # A source Node may intentionally point at an older
                        # immutable output.  Resolve that exact version rather
                        # than silently replacing it with the newest ready row.
                        version_query = version_query.where(
                            AssetVersionRow.version_id == pinned_version
                        )
                    else:
                        version_query = version_query.where(AssetVersionRow.status == "ready")
                        version_query = version_query.order_by(
                            AssetVersionRow.version_no.desc(),
                            AssetVersionRow.version_id.desc(),
                        )
                    pinned_row = (
                        connection.execute(version_query.limit(1)).mappings().one_or_none()
                        if source_row["output_asset_id"] is not None
                        else None
                    )
                    if pinned_version is not None and pinned_row is None:
                        # An explicit source pin is immutable authority, not a
                        # hint.  Never persist a dispatch carrying an
                        # unresolved version id (or silently fall back to a
                        # newer/default AssetVersion).
                        raise _error(
                            "asset_version_not_found",
                            "Node-output Binding references an unknown AssetVersion.",
                        )
                    source = {
                        "node_id": str(source_row["node_id"]),
                        "revision": int(source_row["revision"]),
                        "output_asset_id": source_row["output_asset_id"],
                        "asset_version_id": (
                            pinned_row["version_id"] if pinned_row is not None else pinned_version
                        ),
                        "asset_version_no": (
                            int(pinned_row["version_no"]) if pinned_row is not None else None
                        ),
                        "asset_version_sha256": (
                            pinned_row["sha256"] if pinned_row is not None else None
                        ),
                        "asset_version_status": (
                            pinned_row["status"] if pinned_row is not None else None
                        ),
                        "prompt_digest": source_preparation.get("prompt_digest"),
                        "operation_id": source_preparation.get("operation_id"),
                    }
                elif bool(row["required"]):
                    raise _error(
                        "node_prompt_required_reference_missing",
                        "Required Binding references a missing source Node.",
                    )
            elif row["source_kind"] == "node_output" and bool(row["required"]):
                raise _error(
                    "node_prompt_required_reference_missing",
                    "Required Node-output Binding has no source Node identity.",
                )
            elif row["source_kind"] == "image_asset":
                source = _direct_asset_snapshot_for_binding(connection, row)
            binding_values.append(
                {
                    "binding_id": str(row["binding_id"]),
                    "source_kind": row["source_kind"],
                    "source_node_id": source_node_id,
                    "source_asset_id": row["source_asset_id"],
                    "source_asset_version_id": row["source_asset_version_id"],
                    "target_node_id": str(row["target_node_id"]),
                    "input_role": row["input_role"],
                    "required": bool(row["required"]),
                    "enabled": bool(row["enabled"]),
                    "order_index": int(row["order_index"]),
                    "metadata": metadata,
                    "updated_at": row["updated_at"],
                    "source": source,
                }
            )
    else:
        binding_values = [
            dumped
            for item in bindings
            if (dumped := _safe_model_dump(item)) and dumped.get("enabled", True)
        ]
    return {
        "node_revision": node.revision,
        "output_asset_id": node.output_asset_id,
        "bindings": binding_values,
        "occurrence_id": node.metadata.get("occurrence_id"),
        "character_phase": node.metadata.get("character_phase"),
    }


def _direct_asset_snapshot_for_binding(
    connection: Connection,
    binding_row: Mapping[str, object],
) -> dict[str, object]:
    """Capture an exact immutable AssetVersion for a direct image Binding."""

    asset_id = binding_row.get("source_asset_id")
    version_id = binding_row.get("source_asset_version_id")
    if not isinstance(asset_id, str) or not asset_id:
        raise _error(
            "asset_version_not_found",
            "Direct image Binding has no Asset identity.",
        )
    if not isinstance(version_id, str) or not version_id:
        raise _error(
            "asset_version_not_found",
            "Direct image Binding has no immutable AssetVersion identity.",
        )
    version = (
        connection.execute(
            select(
                AssetVersionRow.asset_id,
                AssetVersionRow.version_id,
                AssetVersionRow.version_no,
                AssetVersionRow.sha256,
                AssetVersionRow.status,
            ).where(
                AssetVersionRow.asset_id == asset_id,
                AssetVersionRow.version_id == version_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if version is None:
        raise _error(
            "asset_version_not_found",
            "Direct image Binding references an unknown AssetVersion.",
        )
    return {
        "asset_id": str(version["asset_id"]),
        "asset_version_id": str(version["version_id"]),
        "asset_version_no": int(version["version_no"]),
        "asset_version_sha256": str(version["sha256"]),
        "asset_version_status": str(version["status"]),
    }


def _assert_node_projection(connection: Connection, node: CanvasNodeV2) -> None:
    """Reject dispatch creation from a stale or non-persisted Node snapshot."""

    row = (
        connection.execute(
            select(
                AgentCanvasNodeRow.revision,
                AgentCanvasNodeRow.execution_mode,
                AgentCanvasNodeRow.prompt_preparation_json,
            ).where(
                AgentCanvasNodeRow.workflow_id == node.workflow_id,
                AgentCanvasNodeRow.node_id == node.node_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _error(
            "prompt_preparation_dispatch_node_missing",
            "Prompt-preparation dispatch requires a persisted Node.",
        )
    if int(row["revision"]) != node.revision or row["execution_mode"] != "generative":
        raise _error(
            "prompt_preparation_dispatch_stale_node",
            "Prompt-preparation dispatch snapshot is stale.",
        )
    persisted = _parse_json_object(row["prompt_preparation_json"])
    if persisted.get("operation_id") != node.prompt_preparation.operation_id:
        raise _error(
            "prompt_preparation_dispatch_stale_node",
            "Prompt-preparation operation does not match the persisted Node.",
        )


def _parse_json_object(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _model_policy_revision(node: CanvasNodeV2) -> int:
    value = node.metadata.get("model_policy_revision")
    if isinstance(value, int) and value >= 1:
        return value
    if node.model_summary is not None:
        return node.model_summary.catalog_revision
    return 1


def _safe_model_dump(value: object) -> dict[str, object]:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _binding_seed_key(value: Mapping[str, object]) -> tuple[int, str]:
    raw_order = value.get("order", value.get("order_index", 0))
    order = raw_order if isinstance(raw_order, int) and not isinstance(raw_order, bool) else 0
    return order, str(value.get("binding_id", ""))


def _coerce_dispatch(
    dispatch: PromptPreparationDispatchV1 | None,
    fields: Mapping[str, object],
    *,
    now: datetime | None,
) -> PromptPreparationDispatchV1:
    if dispatch is not None:
        if fields:
            raise _error(
                "prompt_preparation_dispatch_invalid",
                "Dispatch object and keyword fields cannot be combined.",
            )
        return dispatch
    values = dict(fields)
    if now is not None:
        values.setdefault("available_at", now)
        values.setdefault("created_at", now)
        values.setdefault("updated_at", now)
    try:
        return PromptPreparationDispatchV1.model_validate(values)
    except Exception as error:  # Pydantic's error is not safe to expose as a contract.
        raise _error(
            "prompt_preparation_dispatch_invalid",
            "Prompt-preparation dispatch fields are invalid.",
        ) from error


def _dispatch_values(dispatch: PromptPreparationDispatchV1) -> dict[str, object]:
    return {
        "dispatch_id": dispatch.dispatch_id,
        "workflow_id": dispatch.workflow_id,
        "node_id": dispatch.node_id,
        "node_revision": dispatch.node_revision,
        "operation_id": dispatch.operation_id,
        "logical_key": dispatch.logical_key,
        "role_variant": dispatch.role_variant,
        "occurrence_id": dispatch.occurrence_id,
        "character_phase": dispatch.character_phase,
        "context_snapshot_id": dispatch.context_snapshot_id,
        "context_digest": dispatch.context_digest,
        "context_json": _json(dispatch.context_json),
        "binding_digest": dispatch.binding_digest,
        "recipe_digest": dispatch.recipe_digest,
        "style_projection_digest": dispatch.style_projection_digest,
        "brief_digest": dispatch.brief_digest,
        "requirement_revision_id": dispatch.requirement_revision_id,
        "requirement_revision_no": dispatch.requirement_revision_no,
        "document_revisions_json": _json(dispatch.document_revisions),
        "source_snapshot_json": _json(dispatch.source_snapshot),
        "model_policy_revision": dispatch.model_policy_revision,
        "status": dispatch.status,
        "attempt_count": dispatch.attempt_no,
        "max_attempts": dispatch.max_attempts,
        "available_at": _iso(dispatch.available_at),
        "lease_owner": dispatch.lease_owner,
        "lease_generation": dispatch.lease_generation,
        "lease_expires_at": _iso(dispatch.lease_expires_at) if dispatch.lease_expires_at else None,
        "last_error_code": dispatch.last_error_code,
        "last_error_message": dispatch.last_error_message,
        "supersession_reason": dispatch.supersession_reason,
        "superseded_by_dispatch_id": dispatch.superseded_by_dispatch_id,
        "created_at": _iso(dispatch.created_at),
        "updated_at": _iso(dispatch.updated_at),
        "terminal_at": _iso(dispatch.terminal_at) if dispatch.terminal_at else None,
    }


def _select_one(connection: Connection, dispatch_id: str) -> RowMapping | None:
    return (
        connection.execute(
            select(AgentCanvasPromptPreparationOutboxRow).where(
                AgentCanvasPromptPreparationOutboxRow.dispatch_id == dispatch_id
            )
        )
        .mappings()
        .one_or_none()
    )


def _select_by_logical_key(connection: Connection, logical_key: str) -> RowMapping | None:
    return (
        connection.execute(
            select(AgentCanvasPromptPreparationOutboxRow).where(
                AgentCanvasPromptPreparationOutboxRow.logical_key == logical_key
            )
        )
        .mappings()
        .one_or_none()
    )


def _require_same_identity(
    existing: RowMapping,
    expected: PromptPreparationDispatchV1,
) -> None:
    checks = {
        "workflow_id": expected.workflow_id,
        "node_id": expected.node_id,
        "node_revision": expected.node_revision,
        "operation_id": expected.operation_id,
        "logical_key": expected.logical_key,
        "role_variant": expected.role_variant,
        "occurrence_id": expected.occurrence_id,
        "character_phase": expected.character_phase,
        "context_snapshot_id": expected.context_snapshot_id,
        "context_digest": expected.context_digest,
        "context_json": _json(expected.context_json),
        "binding_digest": expected.binding_digest,
        "recipe_digest": expected.recipe_digest,
        "style_projection_digest": expected.style_projection_digest,
        "brief_digest": expected.brief_digest,
        "requirement_revision_id": expected.requirement_revision_id,
        "requirement_revision_no": expected.requirement_revision_no,
        "document_revisions_json": _json(expected.document_revisions),
        "source_snapshot_json": _json(expected.source_snapshot),
        "model_policy_revision": expected.model_policy_revision,
        "max_attempts": expected.max_attempts,
    }
    if any(existing[field] != value for field, value in checks.items()):
        raise _error(
            "prompt_preparation_dispatch_identity_conflict",
            "Prompt-preparation dispatch identity was reused with different inputs.",
        )


def _dispatch_from_row(row: Mapping[str, Any]) -> PromptPreparationDispatchV1:
    try:
        return PromptPreparationDispatchV1(
            dispatch_id=str(row["dispatch_id"]),
            workflow_id=str(row["workflow_id"]),
            node_id=str(row["node_id"]),
            node_revision=int(row["node_revision"]),
            operation_id=str(row["operation_id"]),
            logical_key=str(row["logical_key"]),
            role_variant=row["role_variant"],
            occurrence_id=row["occurrence_id"],
            character_phase=row["character_phase"],
            context_snapshot_id=row["context_snapshot_id"],
            context_digest=row["context_digest"],
            context_json=json.loads(str(row["context_json"])),
            binding_digest=row["binding_digest"],
            recipe_digest=row["recipe_digest"],
            style_projection_digest=row["style_projection_digest"],
            brief_digest=row["brief_digest"],
            requirement_revision_id=row["requirement_revision_id"],
            requirement_revision_no=(
                int(row["requirement_revision_no"])
                if row["requirement_revision_no"] is not None
                else None
            ),
            document_revisions=json.loads(str(row["document_revisions_json"])),
            source_snapshot=json.loads(str(row["source_snapshot_json"])),
            model_policy_revision=(
                int(row["model_policy_revision"])
                if row["model_policy_revision"] is not None
                else None
            ),
            status=row["status"],
            attempt_no=int(row["attempt_count"]),
            max_attempts=int(row["max_attempts"]),
            available_at=_datetime(row["available_at"]),
            lease_owner=row["lease_owner"],
            lease_generation=int(row["lease_generation"]),
            lease_expires_at=_datetime(row["lease_expires_at"]),
            last_error_code=row["last_error_code"],
            last_error_message=row["last_error_message"],
            supersession_reason=row["supersession_reason"],
            superseded_by_dispatch_id=row["superseded_by_dispatch_id"],
            created_at=_datetime(row["created_at"]),
            updated_at=_datetime(row["updated_at"]),
            terminal_at=_datetime(row["terminal_at"]),
        )
    except V2PersistenceError:
        raise
    except Exception as error:
        raise _error(
            "prompt_preparation_dispatch_corrupt",
            "Prompt-preparation dispatch authority is inconsistent.",
        ) from error


def _require_owned(
    row: Mapping[str, Any],
    worker_id: str,
    lease_generation: int,
    now: datetime,
) -> None:
    if (
        row["status"] != "leased"
        or row["lease_owner"] != worker_id
        or int(row["lease_generation"]) != lease_generation
        or _datetime(row["lease_expires_at"]) is None
        or _datetime(row["lease_expires_at"]) <= now
    ):
        raise _stale_lease()


def _assert_current_node_identity(
    connection: Connection,
    dispatch_row: Mapping[str, Any],
    *,
    node_revision: int | None,
    operation_id: str | None,
    context_digest: str | None,
    source_snapshot: Mapping[str, object] | None,
) -> None:
    """Fence terminal publication against the current Node/input snapshot."""

    row = (
        connection.execute(
            select(AgentCanvasNodeRow).where(
                AgentCanvasNodeRow.workflow_id == dispatch_row["workflow_id"],
                AgentCanvasNodeRow.node_id == dispatch_row["node_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _stale_dispatch()
    persisted_preparation = _parse_json_object(row["prompt_preparation_json"])
    expected_operation = operation_id or str(dispatch_row["operation_id"])
    if persisted_preparation.get("operation_id") != expected_operation:
        raise _stale_dispatch()
    if node_revision is not None and int(dispatch_row["node_revision"]) != node_revision:
        raise _stale_dispatch()
    if context_digest is not None and context_digest != dispatch_row["context_digest"]:
        raise _stale_dispatch()

    # The operation id is derived from the immutable preparation inputs, but a
    # corrupted/legacy writer can still mutate the persisted preparation JSON
    # in place without deriving a successor id.  Compare every identity field
    # that the dispatch row actually froze.  Fields that are intentionally
    # populated by the preparation service (for example recipe/prompt digests
    # on a queued row) are only checked when the dispatch had a non-null value;
    # this keeps the queued -> working -> ready lifecycle valid while fencing
    # an in-place change to an already-bound identity.
    preparation_fields = (
        ("role_variant", "role_variant"),
        ("occurrence_id", "occurrence_id"),
        ("character_phase", "character_phase"),
        ("binding_digest", "binding_digest"),
        ("recipe_digest", "recipe_digest"),
        ("style_projection_digest", "style_projection_digest"),
        ("brief_digest", "brief_digest"),
        ("requirement_revision_id", "requirement_revision_id"),
        ("requirement_revision_no", "requirement_revision_no"),
    )
    for dispatch_field, preparation_field in preparation_fields:
        expected = dispatch_row.get(dispatch_field)
        if expected is not None and persisted_preparation.get(preparation_field) != expected:
            raise _stale_dispatch()

    expected_documents = _parse_json_object(dispatch_row.get("document_revisions_json"))
    if expected_documents:
        current_documents = _parse_json_object(persisted_preparation.get("document_revisions"))
        if current_documents != expected_documents:
            raise _stale_dispatch()

    # Context digest is duplicated in the safe Node metadata after preparation.
    # Do not require it to exist while the row is still queued/working, but do
    # reject a present value that no longer matches the frozen dispatch.
    expected_context_digest = dispatch_row.get("context_digest")
    if expected_context_digest:
        metadata = _parse_json_object(row["metadata_json"])
        current_context_digest = metadata.get("prompt_context_digest")
        if current_context_digest is not None and current_context_digest != expected_context_digest:
            raise _stale_dispatch()

    expected_policy_revision = dispatch_row.get("model_policy_revision")
    if expected_policy_revision is not None:
        current_policy_revision = _current_model_policy_revision(connection, row)
        if current_policy_revision is not None and current_policy_revision != int(
            expected_policy_revision
        ):
            raise _stale_dispatch()
    if source_snapshot is not None:
        current_node = CanvasNodeV2.model_validate(
            {
                "node_id": row["node_id"],
                "workflow_id": row["workflow_id"],
                "node_type": row["node_type"],
                "creative_role": row["creative_role"],
                "role_contract_version": row["role_contract_version"],
                "title": row["title"],
                "status": row["status"],
                "execution_mode": row["execution_mode"],
                "summary_prompt": row["summary_prompt"],
                "generation_prompt": row["generation_prompt"],
                "structured_content": _parse_json_object(row["structured_content_json"]),
                "parameters": _parse_json_object(row["parameters_json"]),
                "metadata": _parse_json_object(row["metadata_json"]),
                "position": {"x": row["position_x"], "y": row["position_y"]},
                "revision": row["revision"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "prompt_preparation": persisted_preparation,
            }
        )
        current_snapshot = _source_snapshot_for_node(connection, current_node, ())
        # The target Node's own lifecycle revision/output are mutable as the
        # preparation service moves queued -> working -> ready.  They are not
        # dependency lineage.  Source node revisions, pinned AssetVersions,
        # binding identities, and occurrence metadata remain in the comparison.
        if _json(_dependency_snapshot(current_snapshot)) != _json(
            _dependency_snapshot(source_snapshot)
        ):
            raise _stale_dispatch()


def _assert_terminal_projection_identity(
    connection: Connection,
    dispatch_row: Mapping[str, Any],
    node: CanvasNodeV2,
) -> None:
    """Fence a terminal Node projection against its immutable dispatch row."""

    preparation = node.prompt_preparation
    expected_context_digest = dispatch_row.get("context_digest")
    if expected_context_digest:
        # Once a dispatch has a frozen context, terminal publication must carry
        # that exact digest in both the preparation projection and the safe
        # metadata written by the preparation service.  An opaque legacy
        # snapshot ID is not sufficient proof for a current terminal result.
        if preparation.context_snapshot_id != expected_context_digest:
            raise _stale_dispatch()
        metadata = _parse_json_object(
            connection.execute(
                select(AgentCanvasNodeRow.metadata_json).where(
                    AgentCanvasNodeRow.workflow_id == node.workflow_id,
                    AgentCanvasNodeRow.node_id == node.node_id,
                )
            ).scalar_one_or_none()
        )
        metadata_context_digest = metadata.get("prompt_context_digest")
        if (
            metadata_context_digest is not None
            and metadata_context_digest != expected_context_digest
        ):
            raise _stale_dispatch()
    _assert_current_node_identity(
        connection,
        dispatch_row,
        operation_id=preparation.operation_id,
        context_digest=(str(expected_context_digest) if expected_context_digest else None),
        source_snapshot=_source_snapshot_for_node(connection, node, ()),
        node_revision=None,
    )


def _dependency_snapshot(value: Mapping[str, object]) -> dict[str, object]:
    """Return only immutable dependency fields from a dispatch snapshot."""

    snapshot = dict(value)
    snapshot.pop("node_revision", None)
    snapshot.pop("output_asset_id", None)
    return snapshot


def _current_model_policy_revision(
    connection: Connection,
    node_row: Mapping[str, Any],
) -> int | None:
    """Resolve the current model-policy revision without exposing catalog data."""

    metadata = _parse_json_object(node_row.get("metadata_json"))
    explicit = metadata.get("model_policy_revision")
    if isinstance(explicit, int) and explicit >= 1:
        return explicit
    model_ref = node_row.get("model_ref")
    if not isinstance(model_ref, str) or not model_ref:
        return 1
    revision = connection.execute(
        select(ProviderModelRow.catalog_revision).where(ProviderModelRow.model_ref == model_ref)
    ).scalar_one_or_none()
    if revision is None:
        return 1
    return int(revision)


def _json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as error:
        raise _error(
            "prompt_preparation_dispatch_invalid",
            "Prompt-preparation dispatch data must be JSON serializable.",
        ) from error


def _json_digest(value: object) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _detached_context(
    context: Mapping[str, object] | None,
) -> tuple[dict[str, object], str | None]:
    """Normalize one immutable context snapshot through the canonical codec."""

    if context is None:
        # Direct/legacy Node writers may not have a Stage context at creation
        # time.  Keep that absence explicit; hashing an empty object would
        # falsely claim immutable context ownership and fence the first worker
        # transition against a snapshot it never received.
        return {}, None
    try:
        return detached_context_payload(context)
    except (TypeError, ValueError) as error:
        raise _error(
            "prompt_preparation_context_invalid",
            "Prompt-preparation context is invalid or exceeds its bounded size.",
        ) from error


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise _error(
            "prompt_preparation_dispatch_time_invalid",
            "Prompt-preparation dispatch time must include a timezone.",
        )
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


def _datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return _utc(datetime.fromisoformat(str(value)))


def _bounded(value: str | None, maximum: int) -> str | None:
    return value[:maximum] if value is not None else None


def _not_found() -> V2PersistenceError:
    return _error(
        "prompt_preparation_dispatch_not_found",
        "Prompt-preparation dispatch was not found.",
    )


def _stale_lease() -> V2PersistenceError:
    return _error(
        "prompt_preparation_dispatch_lease_stale",
        "Prompt-preparation dispatch lease has expired or been superseded.",
    )


def _stale_dispatch() -> V2PersistenceError:
    return _error(
        "prompt_preparation_dispatch_stale",
        "Prompt-preparation dispatch no longer owns the current Node snapshot.",
    )


def _persistence_error() -> V2PersistenceError:
    return _error(
        "prompt_preparation_dispatch_persistence_unavailable",
        "Prompt-preparation dispatch persistence is temporarily unavailable.",
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="prompt_preparation_dispatch")


__all__ = (
    "AgentCanvasPromptPreparationDispatchRepository",
    "AgentCanvasPromptPreparationOutboxRepository",
    "PromptPreparationDispatchRepository",
    "APPLICABLE_NODE_TYPES",
    "normalize_queued_node",
)
