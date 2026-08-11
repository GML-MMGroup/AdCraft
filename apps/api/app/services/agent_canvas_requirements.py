"""Deterministic application service for Agent Canvas Requirement Ledgers."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import TypeAdapter
from sqlalchemy import insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasIdempotencyRow,
    AgentCanvasConceptProposalRow,
    AgentCanvasCreativeMemoryRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasNodeRow,
)
from app.schemas.agent_canvas_requirements import (
    EditableRequirementDirectiveV1,
    ManualRequirementControlPatchV1,
    RequirementApplicationDeltaV1,
    RequirementApplicationResultV1,
    RequirementConflictV1,
    RequirementControlV1,
    RequirementControlPatchV1,
    RequirementDirectiveV1,
    RequirementElementPresencePatchV1,
    RequirementElementPresenceV1,
    RequirementLedgerPatchRequestV1,
    RequirementLedgerResponseV1,
    RequirementLedgerRevisionV1,
    RequirementLedgerV1,
    RequirementPatchV1,
)
from app.schemas.v2_persistence import V2EventInsert
from app.schemas.agent_canvas_creative_session import (
    CreativeElementDecisionV2,
    CreativeGoalV2,
)


_CONTROL_ADAPTER = TypeAdapter(RequirementControlV1)


class AgentCanvasRequirementService:
    """Apply validated requirement changes without invoking an Agent or provider."""

    def __init__(
        self,
        database: V2Database,
        repository: AgentCanvasRequirementRepository,
        events: EventRepository,
    ) -> None:
        if repository.database is not database or events.database is not database:
            raise ValueError("Requirement services must share one V2Database.")
        self._database = database
        self._repository = repository
        self._events = events

    def get_current(self, workflow_id: str) -> RequirementLedgerResponseV1:
        return requirement_response(self._repository.get_current(workflow_id))

    def get_current_revision(self, workflow_id: str) -> RequirementLedgerRevisionV1:
        return self._repository.get_current(workflow_id)

    def editable_directives(
        self,
        workflow_id: str,
        *,
        capability_id: str | None = None,
        mentioned_node_ids: tuple[str, ...] = (),
    ) -> tuple[EditableRequirementDirectiveV1, ...]:
        revision = self._repository.get_current(workflow_id)
        node_ids = set(mentioned_node_ids)
        applicable = [
            item
            for item in revision.ledger.active_directives
            if item.scope_kind == "global"
            or (
                item.scope_kind == "capability"
                and capability_id is not None
                and capability_id in item.capability_ids
            )
            or (item.scope_kind == "node" and bool(node_ids.intersection(item.target_node_ids)))
        ]
        applicable.sort(key=lambda item: (-item.created_revision_no, item.directive_id))
        return tuple(
            EditableRequirementDirectiveV1(
                directive_id=item.directive_id,
                normalized_meaning=item.normalized_meaning,
                scope_kind=item.scope_kind,
                strength=item.strength,
                source_kind=item.source_kind,
            )
            for item in applicable[:32]
        )

    def apply_manual_patch(
        self,
        workflow_id: str,
        *,
        expected_revision_no: int,
        idempotency_key: str,
        request: RequirementLedgerPatchRequestV1,
    ) -> RequirementLedgerResponseV1:
        if not idempotency_key or len(idempotency_key) > 256:
            raise V2PersistenceError(
                "idempotency_key_required",
                "A non-empty Idempotency-Key of at most 256 characters is required.",
                stage="agent_canvas_requirement_service",
            )
        fingerprint = _request_fingerprint(request)
        operation = f"requirement_patch:{workflow_id}"
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    replay = (
                        connection.execute(
                            select(AgentCanvasIdempotencyRow).where(
                                AgentCanvasIdempotencyRow.operation == operation,
                                AgentCanvasIdempotencyRow.idempotency_key == idempotency_key,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if replay is not None:
                        if replay["request_fingerprint"] != fingerprint:
                            raise V2PersistenceError(
                                "idempotency_conflict",
                                "The idempotency key was reused with another request.",
                                stage="agent_canvas_requirement_service",
                            )
                        response = RequirementLedgerResponseV1.model_validate_json(
                            replay["response_json"]
                        )
                        connection.commit()
                        return response

                    current = self._repository.get_current_in_transaction(
                        connection,
                        workflow_id,
                    )
                    if current.revision_no != expected_revision_no:
                        raise V2PersistenceError(
                            "requirement_revision_conflict",
                            "The Requirement Ledger revision is stale.",
                            stage="agent_canvas_requirement_service",
                        )
                    next_ledger, delta = _apply_manual_patch(
                        connection,
                        workflow_id=workflow_id,
                        current=current,
                        request=request,
                    )
                    revision = self._repository.append_in_transaction(
                        connection,
                        workflow_id=workflow_id,
                        expected_revision_no=expected_revision_no,
                        next_ledger=next_ledger,
                        source_kind="manual_edit",
                        created_at=now,
                    )
                    response = requirement_response(revision)
                    if revision.revision_id != current.revision_id:
                        update_requirement_compatibility_projection_in_transaction(
                            connection,
                            workflow_id,
                            revision.ledger,
                            now,
                        )
                        _supersede_stale_proposals(
                            connection,
                            workflow_id,
                            revision.revision_id,
                            now,
                        )
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=workflow_id,
                                event_type="requirement_ledger_updated",
                                created_at=now,
                                payload={
                                    "revision_id": revision.revision_id,
                                    "revision_no": revision.revision_no,
                                    "digest": revision.digest,
                                    "source_kind": "manual_edit",
                                    **delta.model_dump(mode="json"),
                                    "refresh": ["requirements"],
                                },
                            ),
                        )
                    connection.execute(
                        insert(AgentCanvasIdempotencyRow).values(
                            record_id=f"idem_{uuid4().hex}",
                            operation=operation,
                            idempotency_key=idempotency_key,
                            request_fingerprint=fingerprint,
                            response_json=response.model_dump_json(),
                            created_at=now,
                        )
                    )
                    connection.commit()
                    return response
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise V2PersistenceError(
                "requirement_persistence_failed",
                "Requirement Ledger persistence failed.",
                stage="agent_canvas_requirement_service",
            ) from error

    def apply_user_turn_patch(
        self,
        workflow_id: str,
        *,
        expected_revision_no: int,
        source_turn_id: str,
        user_input: str,
        patch: RequirementPatchV1,
        explicit_elements: tuple[RequirementElementPresencePatchV1, ...] = (),
        editable_directive_ids: tuple[str, ...] = (),
    ) -> RequirementApplicationResultV1:
        _validate_model_sources(user_input, patch, explicit_elements)
        if not set(patch.directive_ids_to_supersede) <= set(editable_directive_ids):
            raise V2PersistenceError(
                "requirement_directive_not_found",
                "A superseded Requirement directive is not editable in this turn.",
                stage="agent_canvas_requirement_service",
            )
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current = self._repository.get_current_in_transaction(
                        connection,
                        workflow_id,
                    )
                    if current.revision_no != expected_revision_no:
                        raise V2PersistenceError(
                            "requirement_revision_conflict",
                            "The Requirement Ledger revision is stale.",
                            stage="agent_canvas_requirement_service",
                        )
                    next_ledger, delta = _apply_user_patch(
                        connection,
                        workflow_id=workflow_id,
                        current=current,
                        source_turn_id=source_turn_id,
                        patch=patch,
                        explicit_elements=explicit_elements,
                    )
                    revision = self._repository.append_in_transaction(
                        connection,
                        workflow_id=workflow_id,
                        expected_revision_no=expected_revision_no,
                        next_ledger=next_ledger,
                        source_kind="user_turn",
                        source_turn_id=source_turn_id,
                        created_at=now,
                    )
                    changed = revision.revision_id != current.revision_id
                    if changed:
                        update_requirement_compatibility_projection_in_transaction(
                            connection,
                            workflow_id,
                            revision.ledger,
                            now,
                        )
                        _supersede_stale_proposals(
                            connection,
                            workflow_id,
                            revision.revision_id,
                            now,
                        )
                        self._append_update_event(
                            connection,
                            workflow_id=workflow_id,
                            revision=revision,
                            source_kind="user_turn",
                            delta=delta,
                            created_at=now,
                        )
                    connection.commit()
                    return RequirementApplicationResultV1(
                        revision=revision,
                        delta=delta,
                        changed=changed,
                    )
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise V2PersistenceError(
                "requirement_persistence_failed",
                "Requirement Ledger persistence failed.",
                stage="agent_canvas_requirement_service",
            ) from error

    def _append_update_event(
        self,
        connection,
        *,
        workflow_id: str,
        revision: RequirementLedgerRevisionV1,
        source_kind: str,
        delta: RequirementApplicationDeltaV1,
        created_at: str,
    ) -> None:
        self._events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=workflow_id,
                event_type="requirement_ledger_updated",
                created_at=created_at,
                payload={
                    "revision_id": revision.revision_id,
                    "revision_no": revision.revision_no,
                    "digest": revision.digest,
                    "source_kind": source_kind,
                    **delta.model_dump(mode="json"),
                    "refresh": ["requirements"],
                },
            ),
        )


def requirement_response(
    revision: RequirementLedgerRevisionV1,
) -> RequirementLedgerResponseV1:
    ledger = revision.ledger
    return RequirementLedgerResponseV1(
        workflow_id=revision.workflow_id,
        revision_id=revision.revision_id,
        revision_no=revision.revision_no,
        digest=revision.digest,
        hard_controls=ledger.hard_controls,
        active_directives=ledger.active_directives,
        element_presence=ledger.element_presence,
        unresolved_conflicts=ledger.unresolved_conflicts,
        updated_at=revision.updated_at,
    )


def _apply_manual_patch(
    connection,
    *,
    workflow_id: str,
    current: RequirementLedgerRevisionV1,
    request: RequirementLedgerPatchRequestV1,
) -> tuple[RequirementLedgerV1, RequirementApplicationDeltaV1]:
    current_directives = {item.directive_id: item for item in current.ledger.active_directives}
    missing_directives = sorted(set(request.directive_ids_to_supersede) - current_directives.keys())
    if missing_directives:
        raise V2PersistenceError(
            "requirement_directive_not_found",
            "A superseded Requirement directive was not found.",
            stage="agent_canvas_requirement_service",
            details={"directive_ids": missing_directives},
        )
    _validate_node_scopes(connection, workflow_id, request)

    revision_no = current.revision_no + 1
    controls = {item.control: item for item in current.ledger.hard_controls}
    changed_control_names: list[str] = []
    for patch in request.controls_to_set:
        stored = _stored_control(patch, revision_no)
        controls[stored.control] = stored
        changed_control_names.append(stored.control)

    directives = [
        item
        for item in current.ledger.active_directives
        if item.directive_id not in request.directive_ids_to_supersede
    ]
    added_ids: list[str] = []
    for patch in request.directives_to_add:
        directive_id = f"reqdir_{uuid4().hex}"
        added_ids.append(directive_id)
        directives.append(
            RequirementDirectiveV1(
                directive_id=directive_id,
                source_kind="manual_edit",
                source_text=patch.source_text,
                normalized_meaning=patch.normalized_meaning,
                scope_kind=patch.scope_kind,
                capability_ids=patch.capability_ids,
                target_node_ids=patch.target_node_ids,
                strength=patch.strength,
                created_revision_no=revision_no,
            )
        )
    ledger = current.ledger.model_copy(
        update={
            "hard_controls": tuple(controls[key] for key in sorted(controls)),
            "active_directives": tuple(sorted(directives, key=lambda item: item.directive_id)),
        }
    )
    return ledger, RequirementApplicationDeltaV1(
        changed_control_names=tuple(sorted(changed_control_names)),
        added_directive_ids=tuple(added_ids),
        superseded_directive_ids=request.directive_ids_to_supersede,
    )


def _apply_user_patch(
    connection,
    *,
    workflow_id: str,
    current: RequirementLedgerRevisionV1,
    source_turn_id: str,
    patch: RequirementPatchV1,
    explicit_elements: tuple[RequirementElementPresencePatchV1, ...],
) -> tuple[RequirementLedgerV1, RequirementApplicationDeltaV1]:
    current_directives = {item.directive_id: item for item in current.ledger.active_directives}
    if not set(patch.directive_ids_to_supersede) <= current_directives.keys():
        raise V2PersistenceError(
            "requirement_directive_not_found",
            "A superseded Requirement directive was not found.",
            stage="agent_canvas_requirement_service",
        )
    target_ids = {
        node_id for directive in patch.directives_to_add for node_id in directive.target_node_ids
    }
    _validate_target_ids(connection, workflow_id, target_ids)
    revision_no = current.revision_no + 1

    controls = {item.control: item for item in current.ledger.hard_controls}
    changed_control_names: list[str] = []
    for control_patch in patch.controls_to_set:
        stored = _stored_model_control(control_patch, revision_no, source_turn_id)
        controls[stored.control] = stored
        changed_control_names.append(stored.control)

    directives = [
        item
        for item in current.ledger.active_directives
        if item.directive_id not in patch.directive_ids_to_supersede
    ]
    added_directive_ids: list[str] = []
    for directive_patch in patch.directives_to_add:
        directive_id = f"reqdir_{uuid4().hex}"
        added_directive_ids.append(directive_id)
        directives.append(
            RequirementDirectiveV1(
                directive_id=directive_id,
                source_kind="user_message",
                source_turn_id=source_turn_id,
                source_text=directive_patch.source_quote,
                normalized_meaning=directive_patch.normalized_meaning,
                scope_kind=directive_patch.scope_kind,
                capability_ids=directive_patch.capability_ids,
                target_node_ids=directive_patch.target_node_ids,
                strength=directive_patch.strength,
                created_revision_no=revision_no,
            )
        )

    elements = {item.element_kind: item for item in current.ledger.element_presence}
    for element in explicit_elements:
        elements[element.element_kind] = RequirementElementPresenceV1(
            element_kind=element.element_kind,
            presence=element.presence,
            source_kind="user_message",
            source_turn_id=source_turn_id,
            source_text=element.source_quote,
            created_revision_no=revision_no,
        )

    conflicts = list(current.ledger.unresolved_conflicts)
    conflict_ids: list[str] = []
    for conflict_patch in patch.conflicts:
        conflict_id = f"reqconf_{uuid4().hex}"
        conflict_ids.append(conflict_id)
        conflicts.append(
            RequirementConflictV1(
                conflict_id=conflict_id,
                control_names=conflict_patch.control_names,
                directive_ids=conflict_patch.directive_ids,
                explanation=conflict_patch.explanation,
                source_turn_id=source_turn_id,
                created_revision_no=revision_no,
            )
        )

    ledger = current.ledger.model_copy(
        update={
            "hard_controls": tuple(controls[key] for key in sorted(controls)),
            "active_directives": tuple(sorted(directives, key=lambda item: item.directive_id)),
            "element_presence": tuple(elements[key] for key in sorted(elements)),
            "unresolved_conflicts": tuple(conflicts),
        }
    )
    return ledger, RequirementApplicationDeltaV1(
        changed_control_names=tuple(sorted(changed_control_names)),
        added_directive_ids=tuple(added_directive_ids),
        superseded_directive_ids=patch.directive_ids_to_supersede,
        changed_element_kinds=tuple(sorted(item.element_kind for item in explicit_elements)),
        conflict_ids=tuple(conflict_ids),
    )


def _stored_control(
    patch: ManualRequirementControlPatchV1,
    revision_no: int,
) -> RequirementControlV1:
    return _CONTROL_ADAPTER.validate_python(
        {
            **patch.model_dump(mode="json"),
            "source_kind": "manual_edit",
            "created_revision_no": revision_no,
        }
    )


def _stored_model_control(
    patch: RequirementControlPatchV1,
    revision_no: int,
    source_turn_id: str,
) -> RequirementControlV1:
    payload = patch.model_dump(mode="json")
    source_text = payload.pop("source_quote")
    return _CONTROL_ADAPTER.validate_python(
        {
            **payload,
            "source_kind": "user_message",
            "source_turn_id": source_turn_id,
            "source_text": source_text,
            "created_revision_no": revision_no,
        }
    )


def _validate_node_scopes(
    connection,
    workflow_id: str,
    request: RequirementLedgerPatchRequestV1,
) -> None:
    target_ids = {
        node_id for directive in request.directives_to_add for node_id in directive.target_node_ids
    }
    _validate_target_ids(connection, workflow_id, target_ids)


def _validate_target_ids(connection, workflow_id: str, target_ids: set[str]) -> None:
    if not target_ids:
        return
    existing = set(
        connection.execute(
            select(AgentCanvasNodeRow.node_id).where(
                AgentCanvasNodeRow.workflow_id == workflow_id,
                AgentCanvasNodeRow.node_id.in_(target_ids),
            )
        ).scalars()
    )
    if existing != target_ids:
        raise V2PersistenceError(
            "requirement_scope_invalid",
            "Node-scoped Requirement directives must target this workflow.",
            stage="agent_canvas_requirement_service",
        )


def _validate_model_sources(
    user_input: str,
    patch: RequirementPatchV1,
    explicit_elements: tuple[RequirementElementPresencePatchV1, ...],
) -> None:
    normalized_input = unicodedata.normalize("NFKC", user_input)
    quotes = [item.source_quote for item in patch.controls_to_set]
    quotes.extend(item.source_quote for item in patch.directives_to_add)
    quotes.extend(item.source_quote for item in explicit_elements)
    quotes.extend(
        source_quote for conflict in patch.conflicts for source_quote in conflict.source_quotes
    )
    if any(unicodedata.normalize("NFKC", quote) not in normalized_input for quote in quotes):
        raise V2PersistenceError(
            "requirement_source_quote_invalid",
            "Requirement evidence must quote the current user message exactly.",
            stage="agent_canvas_requirement_service",
        )


def _request_fingerprint(request: RequirementLedgerPatchRequestV1) -> str:
    payload = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def update_requirement_compatibility_projection_in_transaction(
    connection,
    workflow_id: str,
    ledger: RequirementLedgerV1,
    updated_at: str,
    *,
    advance_session_revision: bool = True,
) -> None:
    session = (
        connection.execute(
            select(AgentCanvasGuidanceSessionRow).where(
                AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
            )
        )
        .mappings()
        .one_or_none()
    )
    controls = {item.control: item.value for item in ledger.hard_controls}
    if session is not None:
        goal = CreativeGoalV2.model_validate_json(session["creative_goal_json"])
        projected_goal = goal.model_copy(update={"explicit_constraints": controls})
        existing_elements = tuple(
            CreativeElementDecisionV2.model_validate(item)
            for item in json.loads(session["element_decisions_json"])
        )
        projected_elements = tuple(
            item for item in existing_elements if item.source != "explicit_user"
        ) + tuple(
            CreativeElementDecisionV2(
                element_kind=item.element_kind,
                presence=item.presence,
                authority="user",
                requirements={},
                source="explicit_user",
            )
            for item in ledger.element_presence
        )
        values: dict[str, object] = {
            "creative_goal_json": projected_goal.model_dump_json(),
            "element_decisions_json": json.dumps(
                [item.model_dump(mode="json") for item in projected_elements],
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "updated_at": updated_at,
        }
        if advance_session_revision:
            values["revision"] = int(session["revision"]) + 1
        connection.execute(
            update(AgentCanvasGuidanceSessionRow)
            .where(AgentCanvasGuidanceSessionRow.session_id == session["session_id"])
            .values(**values)
        )
    duration = controls.get("duration_seconds")
    memory_values = {
        "duration_format": str(duration) if duration is not None else "",
        "updated_at": updated_at,
    }
    connection.execute(
        update(AgentCanvasCreativeMemoryRow)
        .where(AgentCanvasCreativeMemoryRow.workflow_id == workflow_id)
        .values(**memory_values)
    )


def _supersede_stale_proposals(
    connection,
    workflow_id: str,
    current_requirement_revision_id: str,
    updated_at: str,
) -> None:
    connection.execute(
        update(AgentCanvasConceptProposalRow)
        .where(
            AgentCanvasConceptProposalRow.workflow_id == workflow_id,
            AgentCanvasConceptProposalRow.availability == "open",
            AgentCanvasConceptProposalRow.requirement_revision_id
            != current_requirement_revision_id,
        )
        .values(availability="superseded", updated_at=updated_at)
    )
