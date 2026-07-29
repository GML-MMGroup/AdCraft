"""SQLite authority for Agent Canvas chat, proposals, and Video Skill Runs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import cast
from uuid import uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasChatEntryRow,
    AgentCanvasChatTurnRow,
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
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_conversation import (
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
        recipe_topics: tuple[str, ...],
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
                    insert(AgentCanvasSkillRunRow).values(
                        skill_run_id=skill_run_id,
                        workflow_id=workflow_id,
                        skill_id=skill_id,
                        skill_version=skill_version,
                        source_skill_run_id=source_skill_run_id,
                        idempotency_key=idempotency_key,
                        created_at=now,
                    )
                )
                for order, topic_id in enumerate(recipe_topics):
                    connection.execute(
                        insert(AgentCanvasPlanningTopicRow).values(
                            skill_run_id=skill_run_id,
                            topic_id=topic_id,
                            display_order=order,
                            status="pending",
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
                return VideoSkillRunV2(
                    skill_run_id=skill_run_id,
                    workflow_id=workflow_id,
                    skill_id=skill_id,
                    skill_version=skill_version,
                    source_skill_run_id=source_skill_run_id,
                    created_at=now,
                )
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

    def complete_turn(self, turn_id: str, *, assistant_message: str | None = None) -> ChatTurnV2:
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
                                metadata_json=_dump({"turn_id": turn_id}),
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
                        status="pending",
                        selected_option_id=None,
                        selection_actor=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                for order, option in enumerate(proposal.options):
                    connection.execute(
                        insert(AgentCanvasConceptOptionRow).values(
                            option_id=option.option_id,
                            proposal_id=proposal_id,
                            display_order=order,
                            title=option.title,
                            description=option.description,
                        )
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
        expected_workflow_revision: int,
        selection_actor: str,
        source_turn_id: str | None,
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
                            created_at=node.created_at.isoformat(),
                            updated_at=node.updated_at.isoformat(),
                        )
                    )
                    snapshot_id = connection.execute(
                        select(AgentCanvasNodeRow.prompt_context_snapshot_id).where(
                            AgentCanvasNodeRow.node_id == node.node_id
                        )
                    ).scalar_one()
                    connection.execute(
                        insert(AgentCanvasPromptContextSnapshotRow).values(
                            snapshot_id=snapshot_id,
                            workflow_id=node.workflow_id,
                            target_node_id=node.node_id,
                            inputs_json="[]",
                            created_at=now,
                        )
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

    def record_expert_activity(
        self,
        turn_id: str,
        *,
        specialist_name: str,
        operation: str,
        status: str,
        label: str,
    ) -> None:
        now = _now()
        try:
            with self._database.engine.begin() as connection:
                turn = _require_turn(connection, turn_id)
                connection.execute(
                    insert(AgentCanvasExpertActivityRow).values(
                        activity_id=f"activity_{uuid4().hex}",
                        turn_id=turn_id,
                        specialist_name=specialist_name,
                        operation=operation,
                        status=status,
                        label=label,
                        created_at=now,
                        updated_at=now,
                    )
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=str(turn["workflow_id"]),
                        event_type=f"expert_activity_{status}",
                        created_at=now,
                        payload={
                            "turn_id": turn_id,
                            "specialist": specialist_name,
                            "operation": operation,
                            "label": label,
                        },
                    ),
                )
        except SQLAlchemyError as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error

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
        return ChatTimelineListResponseV2(
            workflow_id=workflow_id,
            conversation_id=str(conversation_id),
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
                select(AgentCanvasChatEntryRow.entry_id, AgentCanvasChatEntryRow.metadata_json)
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


def _skill_run(row: RowMapping) -> VideoSkillRunV2:
    return VideoSkillRunV2(
        skill_run_id=str(row["skill_run_id"]),
        workflow_id=str(row["workflow_id"]),
        skill_id=str(row["skill_id"]),
        skill_version=str(row["skill_version"]),
        source_skill_run_id=(
            str(row["source_skill_run_id"]) if row["source_skill_run_id"] else None
        ),
        created_at=str(row["created_at"]),
    )


def _planning_topic(row: RowMapping) -> PlanningTopicStateV2:
    return PlanningTopicStateV2(
        skill_run_id=str(row["skill_run_id"]),
        topic_id=str(row["topic_id"]),
        display_order=int(row["display_order"]),
        status=cast(str, row["status"]),
        related_node_ids=tuple(json.loads(str(row["related_node_ids_json"]))),
    )


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
        proposal_kind=cast(str, row["proposal_kind"]),
        specialist_name=cast(str, row["specialist_name"]),
        status=cast(str, row["status"]),
        selected_option_id=(str(row["selected_option_id"]) if row["selected_option_id"] else None),
        selection_actor=cast(str | None, row["selection_actor"]),
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
    return ChatTimelineEntryV2(
        entry_id=str(row["entry_id"]),
        workflow_id=str(row["workflow_id"]),
        conversation_id=str(row["conversation_id"]),
        sequence_no=int(row["sequence_no"]),
        entry_type=cast(str, row["entry_type"]),
        speaker=cast(str | None, row["speaker"]),
        content=str(row["content"]),
        metadata=json.loads(str(row["metadata_json"])),
        created_at=str(row["created_at"]),
    )


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_conversation_repository")
