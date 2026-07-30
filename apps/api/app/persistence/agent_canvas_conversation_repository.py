"""SQLite authority for Agent Canvas chat, proposals, and Video Skill Runs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Mapping, cast
from uuid import uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasActionReceiptRow,
    AgentCanvasChatEntryRow,
    AgentCanvasChatTurnRow,
    AgentCanvasBindingRow,
    AgentCanvasCreativeMemoryRow,
    AgentCanvasConceptOptionRow,
    AgentCanvasConceptProposalRow,
    AgentCanvasConversationRow,
    AgentCanvasExpertActivityRow,
    AgentCanvasNodeRow,
    AgentCanvasPlanningTopicRow,
    AgentCanvasPromptContextSnapshotRow,
    AgentCanvasSkillRunRow,
    AgentCanvasWorkflowRow,
    WorkflowEventRow,
)
from app.schemas.agent_canvas import CanvasBindingV2, CanvasNodeV2
from app.schemas.agent_canvas_conversation import (
    AgentActionReceiptV2,
    ChatTimelineEntryV2,
    ChatTimelineListResponseV2,
    ChatTurnAcceptedV2,
    ChatTurnV2,
    ConceptOptionRecordV2,
    ConceptProposalCreateV2,
    ConceptProposalV2,
    PlanningTopicStateV2,
    ProposalActionRequestV2,
    VideoSkillRunV2,
)
from app.schemas.agent_canvas_creative_session import (
    CreativeSessionStateV2,
    ExpertActivityV2,
    GuidedDeliveryActionV2,
    PlanningTopicProgressV2,
    ProjectCreativeMemoryV2,
    ProposedDraftReferenceV2,
)
from app.schemas.v2_persistence import V2EventInsert


class AgentCanvasConversationRepository:
    """Persist observable Agent conversation state on the canonical V2 database."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Conversation and event repositories must share one database.")
        self._database = database
        self._events = events

    @property
    def database(self) -> V2Database:
        return self._database

    def create_skill_run(
        self,
        workflow_id: str,
        *,
        skill_id: str,
        skill_version: str,
        recipe_topics: tuple[str | Mapping[str, object], ...],
        idempotency_key: str,
        source_skill_run_id: str | None = None,
    ) -> VideoSkillRunV2:
        now = _now()
        try:
            with self._database.engine.begin() as connection:
                existing = (
                    connection.execute(
                        select(AgentCanvasSkillRunRow).where(
                            AgentCanvasSkillRunRow.idempotency_key == idempotency_key
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if (
                        str(existing["workflow_id"]) != workflow_id
                        or str(existing["skill_id"]) != skill_id
                        or str(existing["skill_version"]) != skill_version
                    ):
                        raise _error("idempotency_conflict", "Idempotency key was reused.")
                    return _skill_run(existing)
                _require_workflow(connection, workflow_id)
                skill_run_id = f"skill_run_{uuid4().hex}"
                connection.execute(
                    update(AgentCanvasSkillRunRow)
                    .where(
                        AgentCanvasSkillRunRow.workflow_id == workflow_id,
                        AgentCanvasSkillRunRow.status == "active",
                    )
                    .values(status="superseded", updated_at=now)
                )
                connection.execute(
                    insert(AgentCanvasSkillRunRow).values(
                        skill_run_id=skill_run_id,
                        workflow_id=workflow_id,
                        skill_id=skill_id,
                        skill_version=skill_version,
                        source_skill_run_id=source_skill_run_id,
                        status="active",
                        current_topic_id=(
                            _recipe_topic(recipe_topics[0], 0)["topic_id"]
                            if recipe_topics
                            else None
                        ),
                        deferred_topic_ids_json="[]",
                        memory_revision=_memory_revision(connection, workflow_id),
                        idempotency_key=idempotency_key,
                        created_at=now,
                        updated_at=now,
                    )
                )
                for order, recipe_topic in enumerate(recipe_topics):
                    topic = _recipe_topic(recipe_topic, order)
                    connection.execute(
                        insert(AgentCanvasPlanningTopicRow).values(
                            skill_run_id=skill_run_id,
                            topic_id=topic["topic_id"],
                            topic_kind=topic["topic_kind"],
                            display_order=topic["display_order"],
                            required=topic["required"],
                            specialist_name=topic["specialist_name"],
                            status="pending",
                            outcome=None,
                            related_node_ids_json="[]",
                        )
                    )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        event_type="video_skill_run_created",
                        created_at=now,
                        payload={
                            "skill_run_id": skill_run_id,
                            "skill_id": skill_id,
                            "skill_version": skill_version,
                        },
                    ),
                )
                return self._get_skill_run_in_transaction(connection, skill_run_id)
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error

    def list_planning_topics(self, skill_run_id: str) -> tuple[PlanningTopicStateV2, ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasPlanningTopicRow)
                        .where(AgentCanvasPlanningTopicRow.skill_run_id == skill_run_id)
                        .order_by(AgentCanvasPlanningTopicRow.display_order.asc())
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return tuple(_planning_topic(row) for row in rows)

    def get_skill_run(self, skill_run_id: str) -> VideoSkillRunV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasSkillRunRow).where(
                            AgentCanvasSkillRunRow.skill_run_id == skill_run_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        if row is None:
            raise _error("creative_session_not_found", "Creative session was not found.")
        return _skill_run(row)

    @staticmethod
    def _get_skill_run_in_transaction(
        connection: Connection,
        skill_run_id: str,
    ) -> VideoSkillRunV2:
        row = (
            connection.execute(
                select(AgentCanvasSkillRunRow).where(
                    AgentCanvasSkillRunRow.skill_run_id == skill_run_id
                )
            )
            .mappings()
            .one()
        )
        return _skill_run(row)

    def get_creative_session(self, workflow_id: str) -> CreativeSessionStateV2:
        try:
            with self._database.engine.connect() as connection:
                _require_workflow(connection, workflow_id)
                row = (
                    connection.execute(
                        select(AgentCanvasSkillRunRow)
                        .where(
                            AgentCanvasSkillRunRow.workflow_id == workflow_id,
                            AgentCanvasSkillRunRow.status == "active",
                        )
                        .order_by(AgentCanvasSkillRunRow.updated_at.desc())
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise _error("creative_session_not_found", "Creative session was not found.")
                topic_rows = (
                    connection.execute(
                        select(AgentCanvasPlanningTopicRow)
                        .where(AgentCanvasPlanningTopicRow.skill_run_id == row["skill_run_id"])
                        .order_by(AgentCanvasPlanningTopicRow.display_order.asc())
                    )
                    .mappings()
                    .all()
                )
                memory = _creative_memory(
                    connection.execute(
                        select(AgentCanvasCreativeMemoryRow).where(
                            AgentCanvasCreativeMemoryRow.workflow_id == workflow_id
                        )
                    )
                    .mappings()
                    .one_or_none(),
                    workflow_id,
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        skill_run = _skill_run(row)
        return CreativeSessionStateV2(
            skill_run_id=skill_run.skill_run_id,
            workflow_id=skill_run.workflow_id,
            skill_id=skill_run.skill_id,
            skill_version=skill_run.skill_version,
            status=skill_run.status,
            current_topic_id=skill_run.current_topic_id,
            topics=tuple(_planning_progress(topic) for topic in topic_rows),
            deferred_topic_ids=skill_run.deferred_topic_ids,
            memory_revision=memory.memory_revision,
            updated_at=skill_run.updated_at or skill_run.created_at,
        )

    def get_creative_memory(self, workflow_id: str) -> ProjectCreativeMemoryV2:
        try:
            with self._database.engine.connect() as connection:
                _require_workflow(connection, workflow_id)
                row = (
                    connection.execute(
                        select(AgentCanvasCreativeMemoryRow).where(
                            AgentCanvasCreativeMemoryRow.workflow_id == workflow_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return _creative_memory(row, workflow_id)

    def upsert_creative_memory(
        self,
        memory: ProjectCreativeMemoryV2,
    ) -> ProjectCreativeMemoryV2:
        now = _now()
        try:
            with self._database.engine.begin() as connection:
                _require_workflow(connection, memory.workflow_id)
                current = (
                    connection.execute(
                        select(AgentCanvasCreativeMemoryRow).where(
                            AgentCanvasCreativeMemoryRow.workflow_id == memory.workflow_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                next_revision = (int(current["memory_revision"]) if current else 0) + 1
                values = _creative_memory_values(
                    memory,
                    next_revision,
                    created_at=str(current["created_at"]) if current else now,
                    updated_at=now,
                )
                if current is None:
                    connection.execute(insert(AgentCanvasCreativeMemoryRow).values(**values))
                else:
                    connection.execute(
                        update(AgentCanvasCreativeMemoryRow)
                        .where(AgentCanvasCreativeMemoryRow.workflow_id == memory.workflow_id)
                        .values(**values)
                    )
                connection.execute(
                    update(AgentCanvasSkillRunRow)
                    .where(
                        AgentCanvasSkillRunRow.workflow_id == memory.workflow_id,
                        AgentCanvasSkillRunRow.status == "active",
                    )
                    .values(memory_revision=next_revision, updated_at=now)
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=memory.workflow_id,
                        event_type="creative_memory_updated",
                        created_at=now,
                        payload={"memory_revision": next_revision},
                    ),
                )
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_creative_memory(memory.workflow_id)

    def begin_planning_topic(
        self,
        skill_run_id: str,
        topic_id: str,
    ) -> PlanningTopicStateV2:
        return self._transition_planning_topic(skill_run_id, topic_id, status="working")

    def complete_planning_topic(
        self,
        skill_run_id: str,
        topic_id: str,
        *,
        outcome: str,
        related_node_ids: tuple[str, ...] = (),
    ) -> PlanningTopicStateV2:
        return self._transition_planning_topic(
            skill_run_id,
            topic_id,
            status="completed",
            outcome=outcome,
            related_node_ids=related_node_ids,
        )

    def update_planning_topic(
        self,
        skill_run_id: str,
        topic_id: str,
        *,
        status: str,
        outcome: str | None = None,
    ) -> PlanningTopicStateV2:
        if status not in {
            "pending",
            "working",
            "completed",
            "skipped",
            "deferred",
            "reopened",
        }:
            raise _error("planning_topic_status_invalid", "Planning topic status is invalid.")
        return self._transition_planning_topic(
            skill_run_id,
            topic_id,
            status=status,
            outcome=outcome,
        )

    def reconcile_deleted_memory_nodes(self, workflow_id: str) -> ProjectCreativeMemoryV2:
        now = _now()
        try:
            with self._database.engine.begin() as connection:
                _require_workflow(connection, workflow_id)
                row = (
                    connection.execute(
                        select(AgentCanvasCreativeMemoryRow).where(
                            AgentCanvasCreativeMemoryRow.workflow_id == workflow_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                memory = _creative_memory(row, workflow_id)
                existing_node_ids = {
                    str(node_id)
                    for node_id in connection.execute(
                        select(AgentCanvasNodeRow.node_id).where(
                            AgentCanvasNodeRow.workflow_id == workflow_id
                        )
                    ).scalars()
                }
                approved_node_ids = {
                    role: tuple(node_id for node_id in node_ids if node_id in existing_node_ids)
                    for role, node_ids in memory.approved_node_ids.items()
                }
                approved_node_ids = {
                    role: node_ids for role, node_ids in approved_node_ids.items() if node_ids
                }
                if approved_node_ids == memory.approved_node_ids:
                    return memory
                next_revision = memory.memory_revision + 1
                values = _creative_memory_values(
                    memory.model_copy(update={"approved_node_ids": approved_node_ids}),
                    next_revision,
                    created_at=str(row["created_at"]) if row else now,
                    updated_at=now,
                )
                if row is None:
                    connection.execute(insert(AgentCanvasCreativeMemoryRow).values(**values))
                else:
                    connection.execute(
                        update(AgentCanvasCreativeMemoryRow)
                        .where(AgentCanvasCreativeMemoryRow.workflow_id == workflow_id)
                        .values(**values)
                    )
                connection.execute(
                    update(AgentCanvasSkillRunRow)
                    .where(
                        AgentCanvasSkillRunRow.workflow_id == workflow_id,
                        AgentCanvasSkillRunRow.status == "active",
                    )
                    .values(memory_revision=next_revision, updated_at=now)
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        event_type="creative_memory_updated",
                        created_at=now,
                        payload={
                            "memory_revision": next_revision,
                            "reconciled_deleted_node_references": True,
                        },
                    ),
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_creative_memory(workflow_id)

    def _transition_planning_topic(
        self,
        skill_run_id: str,
        topic_id: str,
        *,
        status: str,
        outcome: str | None = None,
        related_node_ids: tuple[str, ...] | None = None,
    ) -> PlanningTopicStateV2:
        now = _now()
        try:
            with self._database.engine.begin() as connection:
                skill_run = (
                    connection.execute(
                        select(AgentCanvasSkillRunRow).where(
                            AgentCanvasSkillRunRow.skill_run_id == skill_run_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if skill_run is None:
                    raise _error("creative_session_not_found", "Creative session was not found.")
                topic = (
                    connection.execute(
                        select(AgentCanvasPlanningTopicRow).where(
                            AgentCanvasPlanningTopicRow.skill_run_id == skill_run_id,
                            AgentCanvasPlanningTopicRow.topic_id == topic_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if topic is None:
                    raise _error("planning_topic_not_found", "Planning topic was not found.")
                values: dict[str, object] = {"status": status}
                if outcome is not None:
                    values["outcome"] = outcome
                if related_node_ids is not None:
                    existing_related = tuple(
                        str(item) for item in json.loads(str(topic["related_node_ids_json"]))
                    )
                    values["related_node_ids_json"] = _dump(
                        list(dict.fromkeys((*existing_related, *related_node_ids)))
                    )
                next_topic_id = _next_topic_id(connection, skill_run_id, topic_id, status)
                deferred_topic_ids = set(json.loads(str(skill_run["deferred_topic_ids_json"])))
                if status == "deferred":
                    deferred_topic_ids.add(topic_id)
                else:
                    deferred_topic_ids.discard(topic_id)
                connection.execute(
                    update(AgentCanvasPlanningTopicRow)
                    .where(
                        AgentCanvasPlanningTopicRow.skill_run_id == skill_run_id,
                        AgentCanvasPlanningTopicRow.topic_id == topic_id,
                    )
                    .values(**values)
                )
                connection.execute(
                    update(AgentCanvasSkillRunRow)
                    .where(AgentCanvasSkillRunRow.skill_run_id == skill_run_id)
                    .values(
                        current_topic_id=next_topic_id,
                        deferred_topic_ids_json=_dump(sorted(deferred_topic_ids)),
                        updated_at=now,
                    )
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=str(skill_run["workflow_id"]),
                        event_type="planning_topic_updated",
                        created_at=now,
                        payload={
                            "skill_run_id": skill_run_id,
                            "topic_id": topic_id,
                            "status": status,
                            "outcome": outcome,
                            "current_topic_id": next_topic_id,
                        },
                    ),
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return next(
            topic for topic in self.list_planning_topics(skill_run_id) if topic.topic_id == topic_id
        )

    def create_user_turn(
        self,
        workflow_id: str,
        *,
        text: str,
        mentioned_node_ids: tuple[str, ...],
        mentioned_image_asset_ids: tuple[str, ...],
        video_skill_run_id: str | None,
        auto_continue: bool,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        request = {
            "text": text,
            "mentioned_node_ids": list(mentioned_node_ids),
            "mentioned_image_asset_ids": list(mentioned_image_asset_ids),
            "video_skill_run_id": video_skill_run_id,
            "auto_continue": auto_continue,
        }
        return self._create_turn(
            workflow_id,
            turn_kind="message",
            request=request,
            idempotency_key=idempotency_key,
            user_message=text,
        )

    def create_action_turn(
        self,
        workflow_id: str,
        *,
        proposal_id: str,
        action: ProposalActionRequestV2,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        self.get_proposal(proposal_id)
        return self._create_turn(
            workflow_id,
            turn_kind="proposal_action",
            request={
                "proposal_id": proposal_id,
                "action": action.model_dump(mode="json", exclude_none=True),
            },
            idempotency_key=idempotency_key,
            user_message=None,
        )

    def create_command_action_turn(
        self,
        workflow_id: str,
        *,
        plan_id: str,
        action: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        return self._create_turn(
            workflow_id,
            turn_kind="command_action",
            request={
                "plan_id": plan_id,
                "action": action,
                "expected_revision": expected_revision,
            },
            idempotency_key=idempotency_key,
            user_message=None,
        )

    def create_continuation_turn(
        self,
        workflow_id: str,
        *,
        source_action_id: str,
        workflow_revision: int,
        video_skill_run_id: str | None,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        accepted = self._create_turn(
            workflow_id,
            turn_kind="message",
            request={
                "text": "Continue planning from the current canvas state.",
                "mentioned_node_ids": [],
                "mentioned_image_asset_ids": [],
                "video_skill_run_id": video_skill_run_id,
                "auto_continue": False,
                "source_action_id": source_action_id,
            },
            idempotency_key=idempotency_key,
            user_message=None,
        )
        self._events.append(
            V2EventInsert(
                workflow_id=workflow_id,
                event_type="agent_planning_continuation_queued",
                created_at=_now(),
                payload={
                    "source_action_id": source_action_id,
                    "continuation_turn_id": accepted.turn_id,
                    "revision": workflow_revision,
                },
            )
        )
        return accepted

    def _create_turn(
        self,
        workflow_id: str,
        *,
        turn_kind: str,
        request: dict[str, object],
        idempotency_key: str,
        user_message: str | None,
    ) -> ChatTurnAcceptedV2:
        now = _now()
        request_json = _dump(request)
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    existing = (
                        connection.execute(
                            select(AgentCanvasChatTurnRow).where(
                                AgentCanvasChatTurnRow.idempotency_key == idempotency_key
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is not None:
                        if (
                            str(existing["workflow_id"]) != workflow_id
                            or str(existing["request_json"]) != request_json
                        ):
                            raise _error("idempotency_conflict", "Idempotency key was reused.")
                        message_id = self._message_id_for_turn(connection, str(existing["turn_id"]))
                        cursor = self._queued_event_seq(
                            connection,
                            workflow_id,
                            str(existing["turn_id"]),
                        )
                        connection.commit()
                        return ChatTurnAcceptedV2(
                            workflow_id=workflow_id,
                            conversation_id=str(existing["conversation_id"]),
                            message_id=message_id,
                            turn_id=str(existing["turn_id"]),
                            events_cursor=cursor,
                        )
                    conversation_id = _ensure_conversation(connection, workflow_id, now)
                    turn_id = f"turn_{uuid4().hex}"
                    message_id = None
                    if user_message is not None:
                        message_id = f"msg_{uuid4().hex}"
                        connection.execute(
                            insert(AgentCanvasChatEntryRow).values(
                                entry_id=message_id,
                                conversation_id=conversation_id,
                                workflow_id=workflow_id,
                                sequence_no=_next_chat_sequence(connection, conversation_id),
                                entry_type="message",
                                speaker="user",
                                content=user_message,
                                metadata_json=_dump({"turn_id": turn_id}),
                                created_at=now,
                            )
                        )
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=workflow_id,
                                event_type="chat_message_created",
                                created_at=now,
                                payload={
                                    "message_id": message_id,
                                    "turn_id": turn_id,
                                    "speaker": "user",
                                },
                            ),
                        )
                    connection.execute(
                        insert(AgentCanvasChatTurnRow).values(
                            turn_id=turn_id,
                            conversation_id=conversation_id,
                            workflow_id=workflow_id,
                            turn_kind=turn_kind,
                            status="queued",
                            request_json=request_json,
                            idempotency_key=idempotency_key,
                            error_code=None,
                            error_message=None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    queued = self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            event_type="chat_turn_queued",
                            created_at=now,
                            payload={"turn_id": turn_id, "turn_kind": turn_kind},
                        ),
                    )
                    connection.commit()
                    return ChatTurnAcceptedV2(
                        workflow_id=workflow_id,
                        conversation_id=conversation_id,
                        message_id=message_id,
                        turn_id=turn_id,
                        events_cursor=queued.seq,
                    )
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error

    def mark_turn_running(self, turn_id: str) -> ChatTurnV2:
        return self._set_turn_status(turn_id, "running", "chat_turn_started")

    def complete_turn(
        self,
        turn_id: str,
        *,
        assistant_message: str | None = None,
        guided_actions: tuple[GuidedDeliveryActionV2, ...] = (),
    ) -> ChatTurnV2:
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    turn = _require_turn(connection, turn_id)
                    if str(turn["status"]) == "completed":
                        connection.commit()
                        return _turn(turn)
                    if assistant_message:
                        connection.execute(
                            insert(AgentCanvasChatEntryRow).values(
                                entry_id=f"msg_{uuid4().hex}",
                                conversation_id=str(turn["conversation_id"]),
                                workflow_id=str(turn["workflow_id"]),
                                sequence_no=_next_chat_sequence(
                                    connection, str(turn["conversation_id"])
                                ),
                                entry_type="message",
                                speaker="adcraft_video_agent",
                                content=assistant_message,
                                metadata_json=_dump(
                                    {
                                        "turn_id": turn_id,
                                        "guided_actions": [
                                            action.model_dump(mode="json")
                                            for action in guided_actions
                                        ],
                                    }
                                ),
                                created_at=now,
                            )
                        )
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=str(turn["workflow_id"]),
                                event_type="chat_message_created",
                                created_at=now,
                                payload={
                                    "turn_id": turn_id,
                                    "speaker": "adcraft_video_agent",
                                },
                            ),
                        )
                    connection.execute(
                        update(AgentCanvasChatTurnRow)
                        .where(AgentCanvasChatTurnRow.turn_id == turn_id)
                        .values(status="completed", updated_at=now)
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=str(turn["workflow_id"]),
                            event_type="chat_turn_completed",
                            created_at=now,
                            payload={"turn_id": turn_id},
                        ),
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_turn(turn_id)

    def fail_turn(self, turn_id: str, *, code: str, message: str) -> ChatTurnV2:
        now = _now()
        try:
            with self._database.engine.begin() as connection:
                turn = _require_turn(connection, turn_id)
                connection.execute(
                    update(AgentCanvasChatTurnRow)
                    .where(AgentCanvasChatTurnRow.turn_id == turn_id)
                    .values(
                        status="failed",
                        error_code=code,
                        error_message=message,
                        updated_at=now,
                    )
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=str(turn["workflow_id"]),
                        event_type="chat_turn_failed",
                        created_at=now,
                        payload={"turn_id": turn_id, "code": code},
                    ),
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_turn(turn_id)

    def get_turn(self, turn_id: str) -> ChatTurnV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasChatTurnRow).where(
                            AgentCanvasChatTurnRow.turn_id == turn_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        if row is None:
            raise _error("chat_turn_not_found", "Chat turn was not found.")
        return _turn(row)

    def create_proposal(
        self,
        turn_id: str,
        proposal: ConceptProposalCreateV2,
    ) -> ConceptProposalV2:
        now = _now()
        proposal_id = f"proposal_{uuid4().hex}"
        try:
            with self._database.engine.begin() as connection:
                turn = _require_turn(connection, turn_id)
                connection.execute(
                    insert(AgentCanvasConceptProposalRow).values(
                        proposal_id=proposal_id,
                        turn_id=turn_id,
                        workflow_id=str(turn["workflow_id"]),
                        proposal_kind=proposal.proposal_kind,
                        specialist_name=proposal.specialist_name,
                        video_skill_run_id=_turn_skill_run_id(turn),
                        proposal_revision=1,
                        proposed_references_json=_dump(
                            [
                                reference.model_dump(mode="json")
                                for reference in proposal.proposed_references
                            ]
                        ),
                        source_proposal_id=None,
                        publication_identity=None,
                        status="pending",
                        selected_option_id=None,
                        selection_actor=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                reserved_option_ids: set[str] = set()
                for order, option in enumerate(proposal.options):
                    option_id = _available_option_id(
                        connection,
                        requested_id=option.option_id,
                        proposal_id=proposal_id,
                        reserved_ids=reserved_option_ids,
                    )
                    reserved_option_ids.add(option_id)
                    connection.execute(
                        insert(AgentCanvasConceptOptionRow).values(
                            option_id=option_id,
                            proposal_id=proposal_id,
                            display_order=order,
                            title=option.title,
                            description=option.description,
                        )
                    )
                _append_timeline_entry(
                    connection,
                    conversation_id=str(turn["conversation_id"]),
                    workflow_id=str(turn["workflow_id"]),
                    entry_type="concept_proposal",
                    content=f"Review {len(proposal.options)} {proposal.proposal_kind} option(s).",
                    metadata={
                        "proposal_id": proposal_id,
                        "proposal_kind": proposal.proposal_kind,
                        "specialist_name": proposal.specialist_name,
                        "video_skill_run_id": _turn_skill_run_id(turn),
                        "proposal_revision": 1,
                        "proposed_references": [
                            reference.model_dump(mode="json")
                            for reference in proposal.proposed_references
                        ],
                    },
                    created_at=now,
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=str(turn["workflow_id"]),
                        event_type="concept_proposal_created",
                        created_at=now,
                        payload={
                            "turn_id": turn_id,
                            "proposal_id": proposal_id,
                            "specialist": proposal.specialist_name,
                            "option_count": len(proposal.options),
                        },
                    ),
                )
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_proposal(proposal_id)

    def get_proposal(self, proposal_id: str) -> ConceptProposalV2:
        try:
            with self._database.engine.connect() as connection:
                proposal = (
                    connection.execute(
                        select(AgentCanvasConceptProposalRow).where(
                            AgentCanvasConceptProposalRow.proposal_id == proposal_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if proposal is None:
                    raise _error("proposal_not_found", "Concept proposal was not found.")
                options = (
                    connection.execute(
                        select(AgentCanvasConceptOptionRow)
                        .where(AgentCanvasConceptOptionRow.proposal_id == proposal_id)
                        .order_by(AgentCanvasConceptOptionRow.display_order.asc())
                    )
                    .mappings()
                    .all()
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return _proposal(proposal, options)

    def list_pending_proposals(self, workflow_id: str) -> tuple[ConceptProposalV2, ...]:
        try:
            with self._database.engine.connect() as connection:
                ids = list(
                    connection.execute(
                        select(AgentCanvasConceptProposalRow.proposal_id)
                        .where(
                            AgentCanvasConceptProposalRow.workflow_id == workflow_id,
                            AgentCanvasConceptProposalRow.status == "pending",
                        )
                        .order_by(AgentCanvasConceptProposalRow.created_at.asc())
                    ).scalars()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return tuple(self.get_proposal(str(proposal_id)) for proposal_id in ids)

    def mark_proposal(
        self,
        proposal_id: str,
        *,
        status: str,
        selected_option_id: str | None = None,
        selection_actor: str | None = None,
    ) -> ConceptProposalV2:
        now = _now()
        proposal = self.get_proposal(proposal_id)
        if proposal.status != "pending":
            raise _error("proposal_not_pending", "Concept proposal is no longer pending.")
        if selected_option_id and selected_option_id not in {
            option.option_id for option in proposal.options
        }:
            raise _error("proposal_option_not_found", "Concept option was not found.")
        try:
            with self._database.engine.begin() as connection:
                connection.execute(
                    update(AgentCanvasConceptProposalRow)
                    .where(AgentCanvasConceptProposalRow.proposal_id == proposal_id)
                    .values(
                        status=status,
                        selected_option_id=selected_option_id,
                        selection_actor=selection_actor,
                        updated_at=now,
                    )
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=proposal.workflow_id,
                        event_type=f"proposal_{status}",
                        created_at=now,
                        payload={
                            "proposal_id": proposal_id,
                            "option_id": selected_option_id,
                            "selection_actor": selection_actor,
                        },
                    ),
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_proposal(proposal_id)

    def select_and_materialize(
        self,
        proposal_id: str,
        *,
        option_id: str,
        node: CanvasNodeV2,
        bindings: tuple[CanvasBindingV2, ...] = (),
        expected_workflow_revision: int,
        selection_actor: str,
        source_turn_id: str | None,
        publication_identity: str,
        skill_run_id: str | None = None,
        topic_id: str | None = None,
        receipt: AgentActionReceiptV2 | None = None,
    ) -> ConceptProposalV2:
        """Select one option and insert its Draft in one authoring transaction."""

        proposal = self.get_proposal(proposal_id)
        if proposal.status != "pending":
            raise _error("proposal_not_pending", "Concept proposal is no longer pending.")
        if option_id not in {option.option_id for option in proposal.options}:
            raise _error("proposal_option_not_found", "Concept option was not found.")
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current = connection.execute(
                        select(AgentCanvasWorkflowRow.revision).where(
                            AgentCanvasWorkflowRow.workflow_id == proposal.workflow_id
                        )
                    ).scalar_one_or_none()
                    if current != expected_workflow_revision:
                        raise _error(
                            "proposal_revision_conflict",
                            "Workflow changed before proposal materialization.",
                        )
                    connection.execute(
                        insert(AgentCanvasNodeRow).values(
                            node_id=node.node_id,
                            workflow_id=node.workflow_id,
                            node_type=node.node_type,
                            semantic_role=node.semantic_role,
                            role_contract_version=node.role_contract_version,
                            title=node.title,
                            status=node.status,
                            summary_prompt=node.summary_prompt,
                            generation_prompt=node.generation_prompt,
                            structured_content_json=_dump(node.structured_content),
                            model_id=node.model_id,
                            parameters_json=_dump(node.parameters),
                            prompt_context_snapshot_id=(
                                node.prompt_context_snapshot_id or f"snapshot_{uuid4().hex}"
                            ),
                            output_asset_id=node.output_asset_id,
                            video_skill_run_id=node.video_skill_run_id,
                            position_x=node.position.x,
                            position_y=node.position.y,
                            revision=node.revision,
                            error_json=None,
                            derived_from_node_id=None,
                            source_proposal_id=proposal_id,
                            source_option_id=option_id,
                            created_at=node.created_at.isoformat(),
                            updated_at=node.updated_at.isoformat(),
                        )
                    )
                    snapshot_id = connection.execute(
                        select(AgentCanvasNodeRow.prompt_context_snapshot_id).where(
                            AgentCanvasNodeRow.node_id == node.node_id
                        )
                    ).scalar_one()
                    for binding in bindings:
                        if (
                            binding.workflow_id != node.workflow_id
                            or binding.target_node_id != node.node_id
                        ):
                            raise _error(
                                "draft_binding_invalid",
                                "Draft bindings must target the published Draft.",
                            )
                        connection.execute(
                            insert(AgentCanvasBindingRow).values(
                                binding_id=binding.binding_id,
                                workflow_id=binding.workflow_id,
                                source_kind=binding.source.kind,
                                source_node_id=(
                                    binding.source.node_id
                                    if binding.source.kind == "node"
                                    else None
                                ),
                                source_asset_id=(
                                    binding.source.asset_id
                                    if binding.source.kind == "image_asset"
                                    else None
                                ),
                                target_node_id=binding.target_node_id,
                                binding_kind=binding.binding_kind,
                                input_role=binding.input_role,
                                required=binding.required,
                                display_order=binding.display_order,
                                created_at=binding.created_at.isoformat(),
                            )
                        )
                    connection.execute(
                        insert(AgentCanvasPromptContextSnapshotRow).values(
                            snapshot_id=snapshot_id,
                            workflow_id=node.workflow_id,
                            target_node_id=node.node_id,
                            inputs_json=_dump(
                                [
                                    binding.model_dump(mode="json")
                                    for binding in sorted(
                                        bindings,
                                        key=lambda item: (
                                            item.display_order,
                                            item.binding_id,
                                        ),
                                    )
                                ]
                            ),
                            created_at=now,
                        )
                    )
                    if skill_run_id is not None and topic_id is not None:
                        skill_run = (
                            connection.execute(
                                select(AgentCanvasSkillRunRow).where(
                                    AgentCanvasSkillRunRow.skill_run_id == skill_run_id,
                                    AgentCanvasSkillRunRow.workflow_id == node.workflow_id,
                                )
                            )
                            .mappings()
                            .one_or_none()
                        )
                        topic = (
                            connection.execute(
                                select(AgentCanvasPlanningTopicRow).where(
                                    AgentCanvasPlanningTopicRow.skill_run_id == skill_run_id,
                                    AgentCanvasPlanningTopicRow.topic_id == topic_id,
                                )
                            )
                            .mappings()
                            .one_or_none()
                        )
                        if skill_run is not None and topic is not None:
                            related_node_ids = list(
                                dict.fromkeys(
                                    (
                                        *json.loads(str(topic["related_node_ids_json"])),
                                        node.node_id,
                                    )
                                )
                            )
                            next_topic_id = _next_topic_id(
                                connection,
                                skill_run_id,
                                topic_id,
                                "completed",
                            )
                            deferred_topic_ids = set(
                                json.loads(str(skill_run["deferred_topic_ids_json"]))
                            )
                            deferred_topic_ids.discard(topic_id)
                            connection.execute(
                                update(AgentCanvasPlanningTopicRow)
                                .where(
                                    AgentCanvasPlanningTopicRow.skill_run_id == skill_run_id,
                                    AgentCanvasPlanningTopicRow.topic_id == topic_id,
                                )
                                .values(
                                    status="completed",
                                    outcome="selected",
                                    related_node_ids_json=_dump(related_node_ids),
                                )
                            )
                            connection.execute(
                                update(AgentCanvasSkillRunRow)
                                .where(AgentCanvasSkillRunRow.skill_run_id == skill_run_id)
                                .values(
                                    current_topic_id=next_topic_id,
                                    deferred_topic_ids_json=_dump(sorted(deferred_topic_ids)),
                                    updated_at=now,
                                )
                            )
                            self._events.append_in_transaction(
                                connection,
                                V2EventInsert(
                                    workflow_id=node.workflow_id,
                                    event_type="planning_topic_updated",
                                    created_at=now,
                                    payload={
                                        "skill_run_id": skill_run_id,
                                        "topic_id": topic_id,
                                        "status": "completed",
                                        "outcome": "selected",
                                        "current_topic_id": next_topic_id,
                                    },
                                ),
                            )
                            timeline_turn = _require_turn(
                                connection,
                                source_turn_id or proposal.turn_id,
                            )
                            _append_timeline_entry(
                                connection,
                                conversation_id=str(timeline_turn["conversation_id"]),
                                workflow_id=node.workflow_id,
                                entry_type="planning_progress",
                                content=f"Planning topic {topic_id} completed.",
                                metadata={
                                    "skill_run_id": skill_run_id,
                                    "topic_id": topic_id,
                                    "status": "completed",
                                    "outcome": "selected",
                                    "node_id": node.node_id,
                                },
                                created_at=now,
                            )
                    memory_row = (
                        connection.execute(
                            select(AgentCanvasCreativeMemoryRow).where(
                                AgentCanvasCreativeMemoryRow.workflow_id == node.workflow_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    memory = _creative_memory(memory_row, node.workflow_id)
                    approved_node_ids = dict(memory.approved_node_ids)
                    approved_node_ids[node.semantic_role] = tuple(
                        dict.fromkeys(
                            (*approved_node_ids.get(node.semantic_role, ()), node.node_id)
                        )
                    )
                    memory_revision = memory.memory_revision + 1
                    memory_values = _creative_memory_values(
                        memory.model_copy(update={"approved_node_ids": approved_node_ids}),
                        memory_revision,
                        created_at=(
                            str(memory_row["created_at"]) if memory_row is not None else now
                        ),
                        updated_at=now,
                    )
                    if memory_row is None:
                        connection.execute(
                            insert(AgentCanvasCreativeMemoryRow).values(**memory_values)
                        )
                    else:
                        connection.execute(
                            update(AgentCanvasCreativeMemoryRow)
                            .where(AgentCanvasCreativeMemoryRow.workflow_id == node.workflow_id)
                            .values(**memory_values)
                        )
                    if skill_run_id is not None:
                        connection.execute(
                            update(AgentCanvasSkillRunRow)
                            .where(AgentCanvasSkillRunRow.skill_run_id == skill_run_id)
                            .values(memory_revision=memory_revision, updated_at=now)
                        )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=node.workflow_id,
                            event_type="creative_memory_updated",
                            created_at=now,
                            payload={"memory_revision": memory_revision},
                        ),
                    )
                    connection.execute(
                        update(AgentCanvasConceptProposalRow)
                        .where(
                            AgentCanvasConceptProposalRow.proposal_id == proposal_id,
                            AgentCanvasConceptProposalRow.status == "pending",
                        )
                        .values(
                            status="selected",
                            selected_option_id=option_id,
                            selection_actor=selection_actor,
                            publication_identity=publication_identity,
                            updated_at=now,
                        )
                    )
                    connection.execute(
                        update(AgentCanvasWorkflowRow)
                        .where(
                            AgentCanvasWorkflowRow.workflow_id == proposal.workflow_id,
                            AgentCanvasWorkflowRow.revision == expected_workflow_revision,
                        )
                        .values(
                            revision=expected_workflow_revision + 1,
                            updated_at=now,
                        )
                    )
                    if receipt is not None:
                        if (
                            receipt.workflow_id != node.workflow_id
                            or receipt.action_id != source_turn_id
                            or receipt.workflow_revision != expected_workflow_revision + 1
                        ):
                            raise _error(
                                "draft_publication_receipt_invalid",
                                "Draft publication receipt does not match the authoring transaction.",
                            )
                        connection.execute(
                            insert(AgentCanvasActionReceiptRow).values(
                                receipt_id=receipt.receipt_id,
                                workflow_id=receipt.workflow_id,
                                plan_id=None,
                                action_id=receipt.action_id,
                                receipt_json=receipt.model_dump_json(),
                                created_at=now,
                            )
                        )
                        receipt_turn = _require_turn(
                            connection,
                            str(receipt.action_id),
                        )
                        _append_timeline_entry(
                            connection,
                            conversation_id=str(receipt_turn["conversation_id"]),
                            workflow_id=receipt.workflow_id,
                            entry_type="action_receipt",
                            content=receipt.summary,
                            metadata={
                                "action_receipt": receipt.model_dump(mode="json"),
                            },
                            created_at=now,
                        )
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=receipt.workflow_id,
                                event_type="agent_action_receipt_created",
                                created_at=now,
                                payload={
                                    "receipt_id": receipt.receipt_id,
                                    "revision": receipt.workflow_revision,
                                },
                            ),
                        )
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=receipt.workflow_id,
                                event_type="action_receipt_created",
                                created_at=now,
                                payload={
                                    "receipt_id": receipt.receipt_id,
                                    "revision": receipt.workflow_revision,
                                },
                            ),
                        )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=proposal.workflow_id,
                            node_id=node.node_id,
                            event_type="proposal_selected",
                            created_at=now,
                            payload={
                                "proposal_id": proposal_id,
                                "option_id": option_id,
                                "selection_actor": selection_actor,
                                "node_id": node.node_id,
                                "revision": expected_workflow_revision + 1,
                            },
                        ),
                    )
                    if node.node_type == "script":
                        conversation_id = _ensure_conversation(
                            connection,
                            proposal.workflow_id,
                            now,
                        )
                        entry_id = f"artifact_{uuid4().hex}"
                        metadata = {
                            "script_node_id": node.node_id,
                            "source_turn_id": source_turn_id,
                            "action_label": "View Script",
                        }
                        connection.execute(
                            insert(AgentCanvasChatEntryRow).values(
                                entry_id=entry_id,
                                conversation_id=conversation_id,
                                workflow_id=proposal.workflow_id,
                                sequence_no=_next_chat_sequence(
                                    connection,
                                    conversation_id,
                                ),
                                entry_type="script_artifact",
                                speaker=None,
                                content="Script ready",
                                metadata_json=_dump(metadata),
                                created_at=now,
                            )
                        )
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=proposal.workflow_id,
                                node_id=node.node_id,
                                event_type="script_artifact_created",
                                created_at=now,
                                payload={"entry_id": entry_id, **metadata},
                            ),
                        )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_proposal(proposal_id)

    def update_publication_receipt(
        self,
        receipt: AgentActionReceiptV2,
    ) -> AgentActionReceiptV2 | None:
        """Update the one post-commit queue outcome for a published Draft receipt."""

        try:
            with self._database.engine.begin() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasActionReceiptRow).where(
                            AgentCanvasActionReceiptRow.receipt_id == receipt.receipt_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return None
                if str(row["workflow_id"]) != receipt.workflow_id or str(
                    row["action_id"] or ""
                ) != str(receipt.action_id or ""):
                    raise _error(
                        "draft_publication_receipt_invalid",
                        "Draft publication receipt identity does not match.",
                    )
                connection.execute(
                    update(AgentCanvasActionReceiptRow)
                    .where(AgentCanvasActionReceiptRow.receipt_id == receipt.receipt_id)
                    .values(receipt_json=receipt.model_dump_json())
                )
                entries = (
                    connection.execute(
                        select(AgentCanvasChatEntryRow).where(
                            AgentCanvasChatEntryRow.workflow_id == receipt.workflow_id,
                            AgentCanvasChatEntryRow.entry_type == "action_receipt",
                        )
                    )
                    .mappings()
                    .all()
                )
                for entry in entries:
                    metadata = json.loads(str(entry["metadata_json"]))
                    existing = metadata.get("action_receipt")
                    if (
                        not isinstance(existing, dict)
                        or existing.get("receipt_id") != receipt.receipt_id
                    ):
                        continue
                    connection.execute(
                        update(AgentCanvasChatEntryRow)
                        .where(AgentCanvasChatEntryRow.entry_id == entry["entry_id"])
                        .values(
                            content=receipt.summary,
                            metadata_json=_dump(
                                {"action_receipt": receipt.model_dump(mode="json")}
                            ),
                        )
                    )
                    break
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return receipt

    def list_publication_receipts_requiring_recovery(
        self,
    ) -> tuple[tuple[AgentActionReceiptV2, ChatTurnV2], ...]:
        """Return committed receipts with one unfinished post-commit phase."""

        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(
                            AgentCanvasActionReceiptRow.receipt_json,
                            AgentCanvasChatTurnRow.turn_id,
                            AgentCanvasChatTurnRow.workflow_id,
                            AgentCanvasChatTurnRow.conversation_id,
                            AgentCanvasChatTurnRow.status,
                            AgentCanvasChatTurnRow.turn_kind,
                            AgentCanvasChatTurnRow.request_json,
                            AgentCanvasChatTurnRow.error_code,
                            AgentCanvasChatTurnRow.error_message,
                            AgentCanvasChatTurnRow.created_at,
                            AgentCanvasChatTurnRow.updated_at,
                        )
                        .join(
                            AgentCanvasChatTurnRow,
                            AgentCanvasChatTurnRow.turn_id == AgentCanvasActionReceiptRow.action_id,
                        )
                        .where(
                            AgentCanvasActionReceiptRow.plan_id.is_(None),
                            AgentCanvasChatTurnRow.turn_kind.in_(("message", "proposal_action")),
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        recoverable: list[tuple[AgentActionReceiptV2, ChatTurnV2]] = []
        for row in rows:
            receipt = AgentActionReceiptV2.model_validate_json(str(row["receipt_json"]))
            turn = _turn(row)
            if turn.turn_kind == "message":
                if bool(turn.request.get("auto_continue")) and receipt.continuation_turn_id is None:
                    recoverable.append((receipt, turn))
                continue
            try:
                action = ProposalActionRequestV2.model_validate(turn.request["action"])
            except (KeyError, TypeError, ValueError):
                continue
            if action.action == "skip" and receipt.continuation_turn_id is None:
                recoverable.append((receipt, turn))
            elif (
                action.action == "select"
                and action.next_action == "continue_planning"
                and receipt.continuation_turn_id is None
            ):
                recoverable.append((receipt, turn))
            elif (
                action.action == "select"
                and action.next_action == "generate_now"
                and not receipt.queued_execution_ids
            ):
                recoverable.append((receipt, turn))
        return tuple(recoverable)

    def start_expert_activity(
        self,
        turn_id: str,
        *,
        specialist_name: str,
        operation: str,
        label: str,
        event_details: Mapping[str, object] | None = None,
    ) -> ExpertActivityV2:
        now = _now()
        activity_id = _expert_activity_id(turn_id, specialist_name, operation)
        try:
            with self._database.engine.begin() as connection:
                turn = _require_turn(connection, turn_id)
                existing = (
                    connection.execute(
                        select(AgentCanvasExpertActivityRow).where(
                            AgentCanvasExpertActivityRow.activity_id == activity_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    return _expert_activity(existing)
                connection.execute(
                    insert(AgentCanvasExpertActivityRow).values(
                        activity_id=activity_id,
                        turn_id=turn_id,
                        workflow_id=str(turn["workflow_id"]),
                        specialist_name=specialist_name,
                        operation=operation,
                        status="started",
                        label=label,
                        error_code=None,
                        error_message=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=str(turn["workflow_id"]),
                        event_type="expert_activity_started",
                        created_at=now,
                        payload={
                            "activity_id": activity_id,
                            "workflow_id": str(turn["workflow_id"]),
                            "turn_id": turn_id,
                            "specialist_name": specialist_name,
                            "operation": operation,
                            "label": label,
                            "status": "started",
                            "conversation_id": str(turn["conversation_id"]),
                            "created_at": now,
                            **(event_details or {}),
                        },
                    ),
                )
                _append_timeline_entry(
                    connection,
                    conversation_id=str(turn["conversation_id"]),
                    workflow_id=str(turn["workflow_id"]),
                    entry_type="expert_activity",
                    content=label,
                    metadata={
                        "activity_id": activity_id,
                        "specialist_name": specialist_name,
                        "operation": operation,
                        "status": "started",
                        "conversation_id": str(turn["conversation_id"]),
                        "created_at": now,
                        **(event_details or {}),
                    },
                    created_at=now,
                )
                if operation == "materialize_draft":
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=str(turn["workflow_id"]),
                            event_type="draft_materialization_started",
                            created_at=now,
                            payload={
                                "workflow_id": str(turn["workflow_id"]),
                                "turn_id": turn_id,
                                "activity_id": activity_id,
                                "specialist_name": specialist_name,
                                "operation": operation,
                                "status": "started",
                            },
                        ),
                    )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_expert_activity(activity_id)

    def transition_expert_activity(
        self,
        activity_id: str,
        *,
        status: str,
        label: str,
        error_code: str | None = None,
        error_message: str | None = None,
        event_details: Mapping[str, object] | None = None,
    ) -> ExpertActivityV2:
        if status not in {"waiting", "completed", "failed"}:
            raise _error("expert_activity_status_invalid", "Expert activity status is invalid.")
        now = _now()
        try:
            with self._database.engine.begin() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasExpertActivityRow).where(
                            AgentCanvasExpertActivityRow.activity_id == activity_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise _error("expert_activity_not_found", "Expert activity was not found.")
                current_status = str(row["status"])
                if current_status in {"completed", "failed"}:
                    if current_status == status:
                        return _expert_activity(row)
                    raise _error(
                        "expert_activity_terminal",
                        "Expert activity already reached a terminal state.",
                    )
                connection.execute(
                    update(AgentCanvasExpertActivityRow)
                    .where(AgentCanvasExpertActivityRow.activity_id == activity_id)
                    .values(
                        status=status,
                        label=label,
                        error_code=error_code,
                        error_message=error_message,
                        updated_at=now,
                    )
                )
                turn = _require_turn(connection, str(row["turn_id"]))
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=str(row["workflow_id"]),
                        event_type=f"expert_activity_{status}",
                        created_at=now,
                        payload={
                            "activity_id": activity_id,
                            "workflow_id": str(row["workflow_id"]),
                            "turn_id": str(row["turn_id"]),
                            "specialist_name": str(row["specialist_name"]),
                            "operation": str(row["operation"]),
                            "status": status,
                            "label": label,
                            "error_code": error_code,
                            "conversation_id": str(turn["conversation_id"]),
                            "created_at": now,
                            **(event_details or {}),
                        },
                    ),
                )
                _append_timeline_entry(
                    connection,
                    conversation_id=str(turn["conversation_id"]),
                    workflow_id=str(row["workflow_id"]),
                    entry_type="expert_activity",
                    content=label,
                    metadata={
                        "activity_id": activity_id,
                        "specialist_name": str(row["specialist_name"]),
                        "operation": str(row["operation"]),
                        "status": status,
                        "error_code": error_code,
                    },
                    created_at=now,
                )
                if str(row["operation"]) == "materialize_draft":
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=str(row["workflow_id"]),
                            event_type=f"draft_materialization_{status}",
                            created_at=now,
                            payload={
                                "workflow_id": str(row["workflow_id"]),
                                "turn_id": str(row["turn_id"]),
                                "activity_id": activity_id,
                                "specialist_name": str(row["specialist_name"]),
                                "operation": str(row["operation"]),
                                "status": status,
                                "error_code": error_code,
                                "conversation_id": str(turn["conversation_id"]),
                                "created_at": now,
                                **(event_details or {}),
                            },
                        ),
                    )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_expert_activity(activity_id)

    def get_expert_activity(self, activity_id: str) -> ExpertActivityV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasExpertActivityRow).where(
                            AgentCanvasExpertActivityRow.activity_id == activity_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        if row is None:
            raise _error("expert_activity_not_found", "Expert activity was not found.")
        return _expert_activity(row)

    def list_expert_activities(self, turn_id: str) -> tuple[ExpertActivityV2, ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasExpertActivityRow)
                        .where(AgentCanvasExpertActivityRow.turn_id == turn_id)
                        .order_by(AgentCanvasExpertActivityRow.created_at.asc())
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return tuple(_expert_activity(row) for row in rows)

    def record_expert_activity(
        self,
        turn_id: str,
        *,
        specialist_name: str,
        operation: str,
        status: str,
        label: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> ExpertActivityV2:
        activity = self.start_expert_activity(
            turn_id,
            specialist_name=specialist_name,
            operation=operation,
            label=label,
        )
        if status == "started":
            return activity
        return self.transition_expert_activity(
            activity.activity_id,
            status=status,
            label=label,
            error_code=error_code,
            error_message=error_message,
        )

    def list_recoverable_turn_ids(self) -> tuple[str, ...]:
        try:
            with self._database.engine.connect() as connection:
                return tuple(
                    str(value)
                    for value in connection.execute(
                        select(AgentCanvasChatTurnRow.turn_id)
                        .where(AgentCanvasChatTurnRow.status.in_(("queued", "running")))
                        .order_by(AgentCanvasChatTurnRow.created_at.asc())
                    ).scalars()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error

    def list_timeline(
        self,
        workflow_id: str,
        *,
        after_seq: int = 0,
        limit: int = 100,
    ) -> ChatTimelineListResponseV2:
        try:
            with self._database.engine.connect() as connection:
                conversation_id = connection.execute(
                    select(AgentCanvasConversationRow.conversation_id).where(
                        AgentCanvasConversationRow.workflow_id == workflow_id
                    )
                ).scalar_one_or_none()
                if conversation_id is None:
                    return ChatTimelineListResponseV2(
                        workflow_id=workflow_id,
                        conversation_id=None,
                        creative_session=None,
                        next_cursor=after_seq,
                    )
                rows = (
                    connection.execute(
                        select(AgentCanvasChatEntryRow)
                        .where(
                            AgentCanvasChatEntryRow.conversation_id == conversation_id,
                            AgentCanvasChatEntryRow.sequence_no > after_seq,
                        )
                        .order_by(AgentCanvasChatEntryRow.sequence_no.asc())
                        .limit(limit)
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        items = tuple(_timeline_entry(row) for row in rows)
        try:
            creative_session = self.get_creative_session(workflow_id)
        except V2PersistenceError as error:
            if error.code != "creative_session_not_found":
                raise
            creative_session = None
        return ChatTimelineListResponseV2(
            workflow_id=workflow_id,
            conversation_id=str(conversation_id),
            creative_session=creative_session,
            items=items,
            next_cursor=items[-1].sequence_no if items else after_seq,
        )

    def publish_script_artifact(
        self,
        workflow_id: str,
        *,
        script_node_id: str,
        source_turn_id: str | None,
    ) -> ChatTimelineEntryV2:
        now = _now()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    conversation_id = _ensure_conversation(connection, workflow_id, now)
                    existing_rows = (
                        connection.execute(
                            select(AgentCanvasChatEntryRow).where(
                                AgentCanvasChatEntryRow.conversation_id == conversation_id,
                                AgentCanvasChatEntryRow.entry_type == "script_artifact",
                            )
                        )
                        .mappings()
                        .all()
                    )
                    for row in existing_rows:
                        metadata = json.loads(str(row["metadata_json"]))
                        if metadata.get("script_node_id") == script_node_id:
                            connection.commit()
                            return _timeline_entry(row)
                    entry_id = f"artifact_{uuid4().hex}"
                    metadata = {
                        "script_node_id": script_node_id,
                        "source_turn_id": source_turn_id,
                        "action_label": "View Script",
                    }
                    connection.execute(
                        insert(AgentCanvasChatEntryRow).values(
                            entry_id=entry_id,
                            conversation_id=conversation_id,
                            workflow_id=workflow_id,
                            sequence_no=_next_chat_sequence(connection, conversation_id),
                            entry_type="script_artifact",
                            speaker=None,
                            content="Script ready",
                            metadata_json=_dump(metadata),
                            created_at=now,
                        )
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            node_id=script_node_id,
                            event_type="script_artifact_created",
                            created_at=now,
                            payload={"entry_id": entry_id, **metadata},
                        ),
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return next(
            item for item in self.list_timeline(workflow_id).items if item.entry_id == entry_id
        )

    def _set_turn_status(self, turn_id: str, status: str, event_type: str) -> ChatTurnV2:
        now = _now()
        try:
            with self._database.engine.begin() as connection:
                turn = _require_turn(connection, turn_id)
                connection.execute(
                    update(AgentCanvasChatTurnRow)
                    .where(AgentCanvasChatTurnRow.turn_id == turn_id)
                    .values(status=status, updated_at=now)
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=str(turn["workflow_id"]),
                        event_type=event_type,
                        created_at=now,
                        payload={"turn_id": turn_id},
                    ),
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        return self.get_turn(turn_id)

    @staticmethod
    def _message_id_for_turn(connection: Connection, turn_id: str) -> str | None:
        rows = (
            connection.execute(
                select(
                    AgentCanvasChatEntryRow.entry_id, AgentCanvasChatEntryRow.metadata_json
                ).where(AgentCanvasChatEntryRow.speaker == "user")
            )
            .mappings()
            .all()
        )
        for row in rows:
            if json.loads(str(row["metadata_json"])).get("turn_id") == turn_id:
                return str(row["entry_id"])
        return None

    @staticmethod
    def _queued_event_seq(
        connection: Connection,
        workflow_id: str,
        turn_id: str,
    ) -> int:
        rows = (
            connection.execute(
                select(WorkflowEventRow.seq, WorkflowEventRow.payload_json).where(
                    WorkflowEventRow.workflow_id == workflow_id,
                    WorkflowEventRow.event_type == "chat_turn_queued",
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            if json.loads(str(row["payload_json"])).get("turn_id") == turn_id:
                return int(row["seq"])
        raise _error("agent_conversation_unavailable", "Queued turn event was not found.")


def _ensure_conversation(connection: Connection, workflow_id: str, now: str) -> str:
    existing = connection.execute(
        select(AgentCanvasConversationRow.conversation_id).where(
            AgentCanvasConversationRow.workflow_id == workflow_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        return str(existing)
    _require_workflow(connection, workflow_id)
    identity = hashlib.sha256(workflow_id.encode()).hexdigest()[:20]
    conversation_id = f"conv_{identity}"
    connection.execute(
        insert(AgentCanvasConversationRow).values(
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            created_at=now,
            updated_at=now,
        )
    )
    return conversation_id


def _require_workflow(connection: Connection, workflow_id: str) -> None:
    if (
        connection.execute(
            select(AgentCanvasWorkflowRow.workflow_id).where(
                AgentCanvasWorkflowRow.workflow_id == workflow_id
            )
        ).scalar_one_or_none()
        is None
    ):
        raise _error("workflow_not_found", "Workflow was not found.")


def _require_turn(connection: Connection, turn_id: str) -> RowMapping:
    row = (
        connection.execute(
            select(AgentCanvasChatTurnRow).where(AgentCanvasChatTurnRow.turn_id == turn_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _error("chat_turn_not_found", "Chat turn was not found.")
    return row


def _turn_skill_run_id(turn: RowMapping) -> str | None:
    value = json.loads(str(turn["request_json"])).get("video_skill_run_id")
    return str(value) if isinstance(value, str) else None


def _next_chat_sequence(connection: Connection, conversation_id: str) -> int:
    return (
        int(
            connection.execute(
                select(func.coalesce(func.max(AgentCanvasChatEntryRow.sequence_no), 0)).where(
                    AgentCanvasChatEntryRow.conversation_id == conversation_id
                )
            ).scalar_one()
        )
        + 1
    )


def _append_timeline_entry(
    connection: Connection,
    *,
    conversation_id: str,
    workflow_id: str,
    entry_type: str,
    content: str,
    metadata: dict[str, object],
    created_at: str,
) -> None:
    connection.execute(
        insert(AgentCanvasChatEntryRow).values(
            entry_id=f"entry_{uuid4().hex}",
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            sequence_no=_next_chat_sequence(connection, conversation_id),
            entry_type=entry_type,
            speaker=None,
            content=content,
            metadata_json=_dump(metadata),
            created_at=created_at,
        )
    )


def _skill_run(row: RowMapping) -> VideoSkillRunV2:
    return VideoSkillRunV2(
        skill_run_id=str(row["skill_run_id"]),
        workflow_id=str(row["workflow_id"]),
        skill_id=str(row["skill_id"]),
        skill_version=str(row["skill_version"]),
        source_skill_run_id=(
            str(row["source_skill_run_id"]) if row["source_skill_run_id"] else None
        ),
        status=cast(str, row["status"]),
        current_topic_id=(str(row["current_topic_id"]) if row["current_topic_id"] else None),
        deferred_topic_ids=tuple(json.loads(str(row["deferred_topic_ids_json"]))),
        memory_revision=int(row["memory_revision"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _planning_topic(row: RowMapping) -> PlanningTopicStateV2:
    return PlanningTopicStateV2(
        skill_run_id=str(row["skill_run_id"]),
        topic_id=str(row["topic_id"]),
        topic_kind=str(row["topic_kind"]),
        display_order=int(row["display_order"]),
        required=bool(row["required"]),
        specialist_name=cast(str, row["specialist_name"]),
        status=cast(str, row["status"]),
        outcome=str(row["outcome"]) if row["outcome"] else None,
        related_node_ids=tuple(json.loads(str(row["related_node_ids_json"]))),
    )


def _planning_progress(row: RowMapping) -> PlanningTopicProgressV2:
    topic = _planning_topic(row)
    return PlanningTopicProgressV2(
        topic_id=topic.topic_id,
        topic_kind=topic.topic_kind,
        display_order=topic.display_order,
        required=topic.required,
        specialist_name=topic.specialist_name,
        status=topic.status,
        outcome=topic.outcome,
        related_node_ids=topic.related_node_ids,
    )


def _expert_activity(row: RowMapping) -> ExpertActivityV2:
    return ExpertActivityV2(
        activity_id=str(row["activity_id"]),
        workflow_id=str(row["workflow_id"]),
        turn_id=str(row["turn_id"]),
        specialist_name=cast(str, row["specialist_name"]),
        operation=cast(str, row["operation"]),
        status=cast(str, row["status"]),
        error_code=str(row["error_code"]) if row["error_code"] else None,
        error_message=str(row["error_message"]) if row["error_message"] else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _expert_activity_id(turn_id: str, specialist_name: str, operation: str) -> str:
    identity = f"{turn_id}:{specialist_name}:{operation}".encode("utf-8")
    return f"activity_{hashlib.sha256(identity).hexdigest()[:32]}"


def _creative_memory(
    row: RowMapping | None,
    workflow_id: str,
) -> ProjectCreativeMemoryV2:
    if row is None:
        return ProjectCreativeMemoryV2(
            workflow_id=workflow_id,
            memory_revision=0,
            updated_at=_now(),
        )
    return ProjectCreativeMemoryV2(
        workflow_id=str(row["workflow_id"]),
        creative_goal=str(row["creative_goal"]),
        target_audience=str(row["target_audience"]),
        duration_format=str(row["duration_format"]),
        approved_style_summary=str(row["approved_style_summary"]),
        approved_node_ids={
            str(role): tuple(str(node_id) for node_id in node_ids)
            for role, node_ids in json.loads(str(row["approved_node_ids_json"])).items()
        },
        open_questions=tuple(json.loads(str(row["open_questions_json"]))),
        deferred_topics=tuple(json.loads(str(row["deferred_topics_json"]))),
        rejection_notes=tuple(json.loads(str(row["rejection_notes_json"]))),
        conversation_summary=str(row["conversation_summary"]),
        summary_through_sequence_no=int(row["summary_through_sequence_no"]),
        memory_revision=int(row["memory_revision"]),
        updated_at=str(row["updated_at"]),
    )


def _creative_memory_values(
    memory: ProjectCreativeMemoryV2,
    memory_revision: int,
    *,
    created_at: str,
    updated_at: str,
) -> dict[str, object]:
    return {
        "workflow_id": memory.workflow_id,
        "creative_goal": memory.creative_goal,
        "target_audience": memory.target_audience,
        "duration_format": memory.duration_format,
        "approved_style_summary": memory.approved_style_summary,
        "approved_node_ids_json": _dump(memory.approved_node_ids),
        "open_questions_json": _dump(list(memory.open_questions)),
        "deferred_topics_json": _dump(list(memory.deferred_topics)),
        "rejection_notes_json": _dump(list(memory.rejection_notes)),
        "conversation_summary": memory.conversation_summary,
        "summary_through_sequence_no": memory.summary_through_sequence_no,
        "memory_revision": memory_revision,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _memory_revision(connection: Connection, workflow_id: str) -> int:
    value = connection.execute(
        select(AgentCanvasCreativeMemoryRow.memory_revision).where(
            AgentCanvasCreativeMemoryRow.workflow_id == workflow_id
        )
    ).scalar_one_or_none()
    return int(value) if value is not None else 0


def _recipe_topic(
    value: str | Mapping[str, object],
    display_order: int,
) -> dict[str, str | int | bool]:
    source = {"topic_id": value} if isinstance(value, str) else value
    topic_id = str(source["topic_id"])
    return {
        "topic_id": topic_id,
        "topic_kind": str(source.get("topic_kind", topic_id.rstrip("s") or "generic")),
        "display_order": display_order,
        "required": bool(source.get("required", False)),
        "specialist_name": str(source.get("specialist_name", _topic_specialist_name(topic_id))),
    }


def _topic_specialist_name(topic_id: str) -> str:
    return {
        "script": "script_writer",
        "product": "product_designer",
        "props": "prop_designer",
        "characters": "character_designer",
        "scenes": "scene_designer",
        "storyboard": "storyboard_artist",
        "video": "video_director",
        "videos": "video_director",
        "bgm": "bgm_director",
    }.get(topic_id, "script_writer")


def _next_topic_id(
    connection: Connection,
    skill_run_id: str,
    topic_id: str,
    new_status: str,
) -> str | None:
    if new_status not in {"completed", "skipped", "deferred"}:
        return topic_id
    current_order = connection.execute(
        select(AgentCanvasPlanningTopicRow.display_order).where(
            AgentCanvasPlanningTopicRow.skill_run_id == skill_run_id,
            AgentCanvasPlanningTopicRow.topic_id == topic_id,
        )
    ).scalar_one()
    return connection.execute(
        select(AgentCanvasPlanningTopicRow.topic_id)
        .where(
            AgentCanvasPlanningTopicRow.skill_run_id == skill_run_id,
            AgentCanvasPlanningTopicRow.display_order > current_order,
            AgentCanvasPlanningTopicRow.status.not_in(("completed", "skipped")),
        )
        .order_by(AgentCanvasPlanningTopicRow.display_order.asc())
        .limit(1)
    ).scalar_one_or_none()


def _turn(row: RowMapping) -> ChatTurnV2:
    return ChatTurnV2(
        turn_id=str(row["turn_id"]),
        workflow_id=str(row["workflow_id"]),
        conversation_id=str(row["conversation_id"]),
        status=cast(str, row["status"]),
        turn_kind=cast(str, row["turn_kind"]),
        request=json.loads(str(row["request_json"])),
        error_code=str(row["error_code"]) if row["error_code"] else None,
        error_message=str(row["error_message"]) if row["error_message"] else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _proposal(
    row: RowMapping,
    options: list[RowMapping],
) -> ConceptProposalV2:
    return ConceptProposalV2(
        proposal_id=str(row["proposal_id"]),
        workflow_id=str(row["workflow_id"]),
        turn_id=str(row["turn_id"]),
        video_skill_run_id=(
            str(row["video_skill_run_id"]) if row["video_skill_run_id"] is not None else None
        ),
        proposal_revision=int(row["proposal_revision"]),
        source_proposal_id=(
            str(row["source_proposal_id"]) if row["source_proposal_id"] is not None else None
        ),
        proposal_kind=cast(str, row["proposal_kind"]),
        specialist_name=cast(str, row["specialist_name"]),
        status=cast(str, row["status"]),
        selected_option_id=(str(row["selected_option_id"]) if row["selected_option_id"] else None),
        selection_actor=cast(str | None, row["selection_actor"]),
        proposed_references=tuple(
            ProposedDraftReferenceV2.model_validate(item)
            for item in json.loads(str(row["proposed_references_json"]))
        ),
        options=tuple(
            ConceptOptionRecordV2(
                option_id=str(option["option_id"]),
                title=str(option["title"]),
                description=str(option["description"]),
            )
            for option in options
        ),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _timeline_entry(row: RowMapping) -> ChatTimelineEntryV2:
    metadata = json.loads(str(row["metadata_json"]))
    return ChatTimelineEntryV2(
        entry_id=str(row["entry_id"]),
        workflow_id=str(row["workflow_id"]),
        conversation_id=str(row["conversation_id"]),
        sequence_no=int(row["sequence_no"]),
        entry_type=cast(str, row["entry_type"]),
        speaker=cast(str | None, row["speaker"]),
        content=str(row["content"]),
        metadata=metadata,
        command_plan=metadata.get("command_plan"),
        action_receipt=metadata.get("action_receipt"),
        guided_actions=metadata.get("guided_actions", ()),
        created_at=str(row["created_at"]),
    )


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _available_option_id(
    connection: Connection,
    *,
    requested_id: str,
    proposal_id: str,
    reserved_ids: set[str],
) -> str:
    existing = connection.execute(
        select(AgentCanvasConceptOptionRow.option_id).where(
            AgentCanvasConceptOptionRow.option_id == requested_id
        )
    ).scalar_one_or_none()
    if existing is None and requested_id not in reserved_ids:
        return requested_id
    suffix = hashlib.sha256(f"{proposal_id}:{requested_id}".encode()).hexdigest()[:12]
    return f"{requested_id[:147]}_{suffix}"


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_conversation_repository")
