"""SQLite repository for durable Agent Canvas Decision Bundles."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import TypeAdapter
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasChatEntryRow,
    AgentCanvasChatTurnRow,
    AgentCanvasConversationRow,
    AgentCanvasDecisionBundleRow,
    AgentCanvasWorkflowRow,
)
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.schemas.agent_canvas_decision_bundles import (
    CreativeDirectiveDecisionEffectV1,
    DecisionBundleActionAcceptedV1,
    DecisionBundleActionRequestV1,
    DecisionBundleAnswerV1,
    DecisionBundleDraftV1,
    DecisionBundleOptionV1,
    DecisionBundleQuestionV1,
    DecisionBundleV1,
    SetControlDecisionEffectV1,
    SetElementPresenceDecisionEffectV1,
    SubmitDecisionBundleActionV1,
)
from app.schemas.agent_canvas_requirements import (
    RequirementControlV1,
    RequirementDirectiveV1,
    RequirementElementPresenceV1,
    RequirementLedgerV1,
)
from app.schemas.v2_persistence import V2EventInsert


class AgentCanvasDecisionBundleRepository:
    """Persist and reload bounded Decision Bundle aggregate documents."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Decision Bundle and event repositories must share one database.")
        self._database = database
        self._events = events
        self.requirements = AgentCanvasRequirementRepository(database)

    @property
    def database(self) -> V2Database:
        return self._database

    def publish(
        self,
        *,
        workflow_id: str,
        conversation_id: str,
        source_turn_id: str,
        draft: DecisionBundleDraftV1,
    ) -> DecisionBundleV1:
        bundle_id = f"decision_bundle_{uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        questions = tuple(
            DecisionBundleQuestionV1(
                question_id=f"question_{uuid4().hex}",
                prompt=question.prompt,
                selection_mode=question.selection_mode,
                allow_custom_answer=question.allow_custom_answer,
                allow_skip=question.allow_skip,
                options=tuple(
                    DecisionBundleOptionV1(
                        option_id=f"option_{uuid4().hex}",
                        **option.model_dump(mode="python"),
                    )
                    for option in question.options
                ),
            )
            for question in draft.questions
        )
        definition_json = _dump(
            {
                "title": draft.title,
                "introduction": draft.introduction,
                "questions": [question.model_dump(mode="json") for question in questions],
            }
        )
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    _require_publication_scope(
                        connection,
                        workflow_id=workflow_id,
                        conversation_id=conversation_id,
                        source_turn_id=source_turn_id,
                    )
                    previous = (
                        connection.execute(
                            select(AgentCanvasDecisionBundleRow).where(
                                AgentCanvasDecisionBundleRow.conversation_id == conversation_id,
                                AgentCanvasDecisionBundleRow.status == "open",
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if previous is not None:
                        previous_revision = int(previous["revision"]) + 1
                        connection.execute(
                            update(AgentCanvasDecisionBundleRow)
                            .where(
                                AgentCanvasDecisionBundleRow.bundle_id == str(previous["bundle_id"])
                            )
                            .values(
                                status="superseded",
                                revision=previous_revision,
                                updated_at=now,
                                closed_at=now,
                            )
                        )
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=workflow_id,
                                conversation_id=conversation_id,
                                turn_id=source_turn_id,
                                event_type="decision_bundle_superseded",
                                transition_key=(
                                    f"decision-bundle:{previous['bundle_id']}:superseded:"
                                    f"{previous_revision}"
                                ),
                                created_at=now,
                                payload={
                                    "bundle_id": str(previous["bundle_id"]),
                                    "replacement_bundle_id": bundle_id,
                                    "revision": previous_revision,
                                },
                            ),
                        )
                    connection.execute(
                        insert(AgentCanvasDecisionBundleRow).values(
                            bundle_id=bundle_id,
                            workflow_id=workflow_id,
                            conversation_id=conversation_id,
                            source_turn_id=source_turn_id,
                            replacement_bundle_id=None,
                            status="open",
                            revision=1,
                            definition_json=definition_json,
                            answer_json=None,
                            requirement_revision_no=None,
                            idempotency_key=None,
                            request_fingerprint=None,
                            created_at=now,
                            updated_at=now,
                            closed_at=None,
                        )
                    )
                    if previous is not None:
                        connection.execute(
                            update(AgentCanvasDecisionBundleRow)
                            .where(
                                AgentCanvasDecisionBundleRow.bundle_id == str(previous["bundle_id"])
                            )
                            .values(replacement_bundle_id=bundle_id)
                        )
                    sequence_no = (
                        int(
                            connection.execute(
                                select(
                                    func.coalesce(
                                        func.max(AgentCanvasChatEntryRow.sequence_no),
                                        0,
                                    )
                                ).where(AgentCanvasChatEntryRow.conversation_id == conversation_id)
                            ).scalar_one()
                        )
                        + 1
                    )
                    connection.execute(
                        insert(AgentCanvasChatEntryRow).values(
                            entry_id=f"entry_{uuid4().hex}",
                            conversation_id=conversation_id,
                            workflow_id=workflow_id,
                            sequence_no=sequence_no,
                            entry_type="decision_bundle",
                            speaker="adcraft_video_agent",
                            content=draft.introduction,
                            metadata_json=_dump(
                                {
                                    "bundle_id": bundle_id,
                                    "status": "open",
                                    "revision": 1,
                                    "question_count": len(questions),
                                }
                            ),
                            created_at=now,
                        )
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            conversation_id=conversation_id,
                            turn_id=source_turn_id,
                            event_type="decision_bundle_published",
                            transition_key=f"decision-bundle:{bundle_id}:published:1",
                            created_at=now,
                            payload={
                                "bundle_id": bundle_id,
                                "revision": 1,
                                "question_count": len(questions),
                                "status": "open",
                            },
                        ),
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            conversation_id=conversation_id,
                            turn_id=source_turn_id,
                            event_type="decision_bundle_ready",
                            transition_key=f"decision-bundle:{bundle_id}:ready:1",
                            created_at=now,
                            payload={
                                "bundle_id": bundle_id,
                                "revision": 1,
                                "question_count": len(questions),
                                "status": "open",
                            },
                        ),
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise V2PersistenceError(
                "decision_bundle_persistence_unavailable",
                "Decision Bundle storage failed.",
                stage="decision_bundle_repository",
            ) from error
        return self.get(workflow_id, bundle_id)

    def get(self, workflow_id: str, bundle_id: str) -> DecisionBundleV1:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasDecisionBundleRow).where(
                            AgentCanvasDecisionBundleRow.workflow_id == workflow_id,
                            AgentCanvasDecisionBundleRow.bundle_id == bundle_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise V2PersistenceError(
                "decision_bundle_persistence_unavailable",
                "Decision Bundle storage failed.",
                stage="decision_bundle_repository",
            ) from error
        if row is None:
            raise V2PersistenceError(
                "decision_bundle_not_found",
                "Decision Bundle was not found.",
                stage="decision_bundle_repository",
            )
        return _bundle(row)

    def get_open_for_conversation(self, conversation_id: str) -> DecisionBundleV1 | None:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasDecisionBundleRow).where(
                            AgentCanvasDecisionBundleRow.conversation_id == conversation_id,
                            AgentCanvasDecisionBundleRow.status == "open",
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise V2PersistenceError(
                "decision_bundle_persistence_unavailable",
                "Decision Bundle storage failed.",
                stage="decision_bundle_repository",
            ) from error
        return _bundle(row) if row is not None else None

    def apply_action(
        self,
        *,
        workflow_id: str,
        bundle_id: str,
        action: DecisionBundleActionRequestV1,
        idempotency_key: str,
    ) -> DecisionBundleActionAcceptedV1:
        if not idempotency_key or len(idempotency_key) > 256:
            raise _decision_error(
                "idempotency_key_required",
                "A non-empty Idempotency-Key of at most 256 characters is required.",
            )
        fingerprint = hashlib.sha256(
            _dump(action.model_dump(mode="json")).encode("utf-8")
        ).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    row = (
                        connection.execute(
                            select(AgentCanvasDecisionBundleRow).where(
                                AgentCanvasDecisionBundleRow.workflow_id == workflow_id,
                                AgentCanvasDecisionBundleRow.bundle_id == bundle_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise _decision_error(
                            "decision_bundle_not_found", "Decision Bundle was not found."
                        )
                    if row["idempotency_key"] == idempotency_key:
                        if row["request_fingerprint"] != fingerprint:
                            raise _decision_error(
                                "idempotency_conflict",
                                "The idempotency key was reused with another request.",
                            )
                        stored = json.loads(str(row["answer_json"]))
                        accepted = DecisionBundleActionAcceptedV1.model_validate(
                            stored["accepted"]
                        ).model_copy(update={"replayed": True})
                        connection.commit()
                        return accepted
                    if str(row["status"]) != "open":
                        raise _decision_error(
                            "decision_bundle_closed", "Decision Bundle is already closed."
                        )
                    if int(row["revision"]) != action.expected_revision:
                        raise _decision_error(
                            "decision_bundle_revision_conflict",
                            "Decision Bundle revision is stale.",
                        )
                    bundle = _bundle(row)
                    answers = _validate_answers(bundle, action)
                    current = self.requirements.get_current_in_transaction(connection, workflow_id)
                    next_ledger = _apply_answers_to_ledger(
                        current.ledger,
                        bundle=bundle,
                        answers=answers,
                        next_revision_no=current.revision_no + 1,
                    )
                    next_revision = self.requirements.append_in_transaction(
                        connection,
                        workflow_id=workflow_id,
                        expected_revision_no=current.revision_no,
                        next_ledger=next_ledger,
                        source_kind="decision_bundle_answer",
                        source_turn_id=bundle.source_turn_id,
                        source_bundle_id=bundle.bundle_id,
                        created_at=now,
                    )
                    turn_id = f"turn_{uuid4().hex}"
                    connection.execute(
                        insert(AgentCanvasChatTurnRow).values(
                            turn_id=turn_id,
                            conversation_id=bundle.conversation_id,
                            workflow_id=workflow_id,
                            turn_kind="message",
                            status="queued",
                            request_json=_dump(
                                {
                                    "text": (
                                        "Continue guided production from the accepted "
                                        "Decision Bundle."
                                    ),
                                    "bundle_id": bundle_id,
                                    "bundle_revision": bundle.revision + 1,
                                    "requirement_revision_no": next_revision.revision_no,
                                    "schema_version": "1",
                                }
                            ),
                            idempotency_key=f"decision-bundle-continuation:{idempotency_key}",
                            error_code=None,
                            error_message=None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    event_type = (
                        "decision_bundle_answered"
                        if isinstance(action, SubmitDecisionBundleActionV1)
                        else "decision_bundle_skipped"
                    )
                    status = "answered" if answers else "skipped"
                    event = self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            conversation_id=bundle.conversation_id,
                            turn_id=turn_id,
                            event_type=event_type,
                            transition_key=(
                                f"decision-bundle:{bundle_id}:{status}:{bundle.revision + 1}"
                            ),
                            created_at=now,
                            payload={
                                "bundle_id": bundle_id,
                                "revision": bundle.revision + 1,
                                "requirement_revision_no": next_revision.revision_no,
                                "turn_id": turn_id,
                            },
                        ),
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            conversation_id=bundle.conversation_id,
                            turn_id=turn_id,
                            event_type="agent_turn_queued",
                            transition_key=f"decision-bundle:{bundle_id}:turn:{turn_id}",
                            created_at=now,
                            payload={
                                "turn_id": turn_id,
                                "turn_kind": "message",
                                "bundle_id": bundle_id,
                            },
                        ),
                    )
                    accepted = DecisionBundleActionAcceptedV1(
                        workflow_id=workflow_id,
                        bundle_id=bundle_id,
                        status=status,
                        revision=bundle.revision + 1,
                        requirement_revision_no=next_revision.revision_no,
                        turn_id=turn_id,
                        events_cursor=event.seq,
                    )
                    connection.execute(
                        update(AgentCanvasDecisionBundleRow)
                        .where(AgentCanvasDecisionBundleRow.bundle_id == bundle_id)
                        .values(
                            status=status,
                            revision=bundle.revision + 1,
                            answer_json=_dump(
                                {
                                    "answers": [
                                        answer.model_dump(mode="json") for answer in answers
                                    ],
                                    "accepted": accepted.model_dump(mode="json"),
                                }
                            ),
                            requirement_revision_no=next_revision.revision_no,
                            idempotency_key=idempotency_key,
                            request_fingerprint=fingerprint,
                            updated_at=now,
                            closed_at=now,
                        )
                    )
                    timeline_rows = connection.execute(
                        select(
                            AgentCanvasChatEntryRow.entry_id,
                            AgentCanvasChatEntryRow.metadata_json,
                        ).where(
                            AgentCanvasChatEntryRow.conversation_id == bundle.conversation_id,
                            AgentCanvasChatEntryRow.entry_type == "decision_bundle",
                        )
                    ).mappings()
                    for timeline_row in timeline_rows:
                        metadata = json.loads(str(timeline_row["metadata_json"]))
                        if metadata.get("bundle_id") != bundle_id:
                            continue
                        connection.execute(
                            update(AgentCanvasChatEntryRow)
                            .where(
                                AgentCanvasChatEntryRow.entry_id == str(timeline_row["entry_id"])
                            )
                            .values(
                                metadata_json=_dump(
                                    {
                                        **metadata,
                                        "status": status,
                                        "revision": bundle.revision + 1,
                                    }
                                )
                            )
                        )
                    connection.commit()
                    return accepted
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise V2PersistenceError(
                "decision_bundle_persistence_unavailable",
                "Decision Bundle storage failed.",
                stage="decision_bundle_repository",
            ) from error


def _require_publication_scope(
    connection,
    *,
    workflow_id: str,
    conversation_id: str,
    source_turn_id: str,
) -> None:
    workflow = connection.execute(
        select(AgentCanvasWorkflowRow.workflow_id).where(
            AgentCanvasWorkflowRow.workflow_id == workflow_id
        )
    ).scalar_one_or_none()
    conversation = connection.execute(
        select(AgentCanvasConversationRow.workflow_id).where(
            AgentCanvasConversationRow.conversation_id == conversation_id
        )
    ).scalar_one_or_none()
    turn = (
        connection.execute(
            select(
                AgentCanvasChatTurnRow.workflow_id,
                AgentCanvasChatTurnRow.conversation_id,
            ).where(AgentCanvasChatTurnRow.turn_id == source_turn_id)
        )
        .mappings()
        .one_or_none()
    )
    if (
        workflow is None
        or conversation != workflow_id
        or turn is None
        or str(turn["workflow_id"]) != workflow_id
        or str(turn["conversation_id"]) != conversation_id
    ):
        raise V2PersistenceError(
            "decision_bundle_publication_scope_invalid",
            "Decision Bundle publication scope is invalid.",
            stage="decision_bundle_repository",
        )


def _bundle(row: RowMapping) -> DecisionBundleV1:
    definition = json.loads(str(row["definition_json"]))
    answer_payload = json.loads(str(row["answer_json"])) if row["answer_json"] is not None else []
    answers = (
        answer_payload.get("answers", []) if isinstance(answer_payload, dict) else answer_payload
    )
    return DecisionBundleV1.model_validate(
        {
            "bundle_id": row["bundle_id"],
            "workflow_id": row["workflow_id"],
            "conversation_id": row["conversation_id"],
            "source_turn_id": row["source_turn_id"],
            "replacement_bundle_id": row["replacement_bundle_id"],
            "status": row["status"],
            "revision": row["revision"],
            "title": definition["title"],
            "introduction": definition["introduction"],
            "questions": definition["questions"],
            "answers": answers,
            "requirement_revision_no": row["requirement_revision_no"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "closed_at": row["closed_at"],
        }
    )


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _decision_error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="decision_bundle_repository")


def _validate_answers(
    bundle: DecisionBundleV1,
    action: DecisionBundleActionRequestV1,
) -> tuple[DecisionBundleAnswerV1, ...]:
    if not isinstance(action, SubmitDecisionBundleActionV1):
        return ()
    by_question = {question.question_id: question for question in bundle.questions}
    answer_ids = [answer.question_id for answer in action.answers]
    if len(answer_ids) != len(set(answer_ids)) or set(answer_ids) != set(by_question):
        raise _decision_error(
            "decision_bundle_answer_invalid",
            "Every Decision Bundle question must be answered exactly once.",
        )
    for answer in action.answers:
        question = by_question[answer.question_id]
        options = {option.option_id: option for option in question.options}
        if answer.selected_option_ids:
            if any(option_id not in options for option_id in answer.selected_option_ids):
                raise _decision_error(
                    "decision_bundle_answer_invalid",
                    "Decision Bundle answer references an unknown option.",
                )
            if question.selection_mode == "single" and len(answer.selected_option_ids) != 1:
                raise _decision_error(
                    "decision_bundle_answer_invalid",
                    "Single-select Decision Bundle questions require one option.",
                )
        elif answer.custom_answer is not None and not question.allow_custom_answer:
            raise _decision_error(
                "decision_bundle_answer_invalid",
                "This Decision Bundle question does not allow a custom answer.",
            )
        elif answer.skipped and not question.allow_skip:
            raise _decision_error(
                "decision_bundle_answer_invalid",
                "This Decision Bundle question cannot be skipped.",
            )
    return action.answers


def _apply_answers_to_ledger(
    ledger: RequirementLedgerV1,
    *,
    bundle: DecisionBundleV1,
    answers: tuple[DecisionBundleAnswerV1, ...],
    next_revision_no: int,
) -> RequirementLedgerV1:
    controls = {item.control: item for item in ledger.hard_controls}
    directives = list(ledger.active_directives)
    elements = {item.element_kind: item for item in ledger.element_presence}
    assigned_controls: dict[str, object] = {}
    by_question = {question.question_id: question for question in bundle.questions}
    for answer in answers:
        question = by_question[answer.question_id]
        by_option = {option.option_id: option for option in question.options}
        for option_id in answer.selected_option_ids:
            option = by_option[option_id]
            for effect in option.effects:
                provenance = {
                    "source_kind": "decision_bundle_answer",
                    "source_turn_id": bundle.source_turn_id,
                    "source_bundle_id": bundle.bundle_id,
                    "source_question_id": question.question_id,
                    "source_option_id": option.option_id,
                    "source_text": "Decision Bundle option selection",
                    "created_revision_no": next_revision_no,
                }
                if isinstance(effect, SetControlDecisionEffectV1):
                    prior = assigned_controls.get(effect.control)
                    if prior is not None and prior != effect.value:
                        raise _decision_error(
                            "decision_bundle_answer_invalid",
                            "Selected Decision Bundle options set conflicting controls.",
                        )
                    assigned_controls[effect.control] = effect.value
                    try:
                        controls[effect.control] = TypeAdapter(
                            RequirementControlV1
                        ).validate_python(
                            {"control": effect.control, "value": effect.value, **provenance}
                        )
                    except ValueError as error:
                        raise _decision_error(
                            "decision_bundle_effect_invalid",
                            "Decision Bundle control effect is invalid.",
                        ) from error
                elif isinstance(effect, CreativeDirectiveDecisionEffectV1):
                    directives.append(
                        RequirementDirectiveV1(
                            directive_id=f"directive_{uuid4().hex}",
                            normalized_meaning=effect.directive,
                            scope_kind=effect.scope_kind,
                            capability_ids=effect.capability_ids,
                            target_node_ids=(),
                            strength="preference",
                            **provenance,
                        )
                    )
                elif isinstance(effect, SetElementPresenceDecisionEffectV1):
                    elements[effect.element_kind] = RequirementElementPresenceV1(
                        element_kind=effect.element_kind,
                        presence=effect.presence,
                        **provenance,
                    )
        if answer.custom_answer is not None:
            directives.append(
                RequirementDirectiveV1(
                    directive_id=f"directive_{uuid4().hex}",
                    source_kind="decision_bundle_answer",
                    source_turn_id=bundle.source_turn_id,
                    source_bundle_id=bundle.bundle_id,
                    source_question_id=question.question_id,
                    source_option_id=None,
                    source_text=answer.custom_answer,
                    normalized_meaning=answer.custom_answer,
                    scope_kind="global",
                    capability_ids=(),
                    target_node_ids=(),
                    strength="preference",
                    created_revision_no=next_revision_no,
                )
            )
    return ledger.model_copy(
        update={
            "hard_controls": tuple(controls.values()),
            "active_directives": tuple(directives),
            "element_presence": tuple(elements.values()),
        }
    )
