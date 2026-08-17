"""Atomic persistence for Storyboard prompt-ready runnable authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from hashlib import sha256
import json

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.agent_canvas_auto_run_repository import (
    AgentCanvasAutomaticRunRepository,
)
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasAutomaticRunCommandRow,
    AgentCanvasBindingRow,
    AgentCanvasChatTurnRow,
    AgentCanvasExecutionSettingsRow,
    AgentCanvasGuidanceAwaitingRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasMaterializationCommitRow,
    AgentCanvasNodeRow,
    AgentCanvasWorkflowRow,
    AgentWorkingDocumentRow,
)
from app.schemas.agent_canvas_guided_checkpoint import (
    GuidedCheckpointOriginV1,
    guided_checkpoint_id,
)
from app.schemas.agent_canvas_materialization_commit import MaterializationOutcomeV1
from app.schemas.agent_canvas_production_journey import GuidedProductionJourneyV1
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1
from app.schemas.agent_canvas_storyboard_prompt_ready_promotion import (
    StoryboardPromptReadyPromotionCommandV1,
    StoryboardPromptReadyPromotionResultV1,
)
from app.schemas.v2_persistence import V2EventInsert


FaultInjector = Callable[[str], None]


class StoryboardPromptReadyPromotionRepository:
    """Validate and publish one exact Storyboard runnable checkpoint."""

    def __init__(
        self,
        database: V2Database,
        events: EventRepository,
        *,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        if events.database is not database:
            raise ValueError("Storyboard promotion and events must share one database.")
        self._database = database
        self._events = events
        self._automatic_runs = AgentCanvasAutomaticRunRepository(database, events)
        self._fault_injector = fault_injector

    def promote(
        self,
        command: StoryboardPromptReadyPromotionCommandV1,
    ) -> StoryboardPromptReadyPromotionResultV1:
        now = datetime.now(timezone.utc)
        checkpoint_id = guided_checkpoint_id(
            command.workflow_id,
            command.session_id,
            stage_revision=command.expected_stage_revision,
        )
        action_id = (
            f"storyboard-prompt-ready:{command.materialization_id}:"
            f"{command.expected_stage_revision}"
        )
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    materialization = self._materialization(connection, command)
                    session = self._session(connection, command)
                    existing = self._replay_result(
                        connection,
                        command=command,
                        session=session,
                        checkpoint_id=checkpoint_id,
                        action_id=action_id,
                    )
                    if existing is not None:
                        connection.rollback()
                        return existing

                    workflow_revision = connection.execute(
                        select(AgentCanvasWorkflowRow.revision).where(
                            AgentCanvasWorkflowRow.workflow_id == command.workflow_id
                        )
                    ).scalar_one_or_none()
                    if workflow_revision != command.expected_workflow_revision:
                        raise _stale("workflow_revision")
                    if int(session["revision"]) != command.expected_session_revision:
                        raise _stale("session_revision")
                    journey = GuidedProductionJourneyV1.model_validate_json(
                        str(session["journey_state_json"])
                    )
                    if (
                        journey.stage != "storyboard_grids"
                        or journey.stage_status != "working"
                        or journey.stage_revision != command.expected_stage_revision
                        or journey.active_action is not None
                    ):
                        raise _stale("journey_stage")
                    if (
                        connection.execute(
                            select(AgentCanvasGuidanceAwaitingRow.awaiting_id).where(
                                AgentCanvasGuidanceAwaitingRow.workflow_id == command.workflow_id
                            )
                        ).scalar_one_or_none()
                        is not None
                    ):
                        raise _stale("guidance_awaiting")

                    self._validate_materialization_outcome(materialization, command)
                    self._validate_production_plan(connection, command)
                    node_rows = self._validate_nodes(connection, command)
                    self._validate_execution_mode(connection, command)

                    origin = GuidedCheckpointOriginV1(
                        checkpoint_id=checkpoint_id,
                        guidance_session_id=command.session_id,
                        stage_revision=command.expected_stage_revision,
                    )
                    timestamp = now.isoformat()
                    for pair, row in zip(command.preparations, node_rows, strict=True):
                        metadata = json.loads(str(row["metadata_json"]))
                        metadata["guided_checkpoint"] = origin.model_dump(mode="json")
                        updated = connection.execute(
                            update(AgentCanvasNodeRow)
                            .where(
                                AgentCanvasNodeRow.workflow_id == command.workflow_id,
                                AgentCanvasNodeRow.node_id == pair.node_id,
                                AgentCanvasNodeRow.revision == pair.expected_node_revision,
                            )
                            .values(
                                metadata_json=_dump(metadata),
                                revision=pair.expected_node_revision + 1,
                                updated_at=timestamp,
                            )
                        )
                        if updated.rowcount != 1:
                            raise _stale("node_revision")
                    self._fault("node")

                    next_journey = (
                        journey.model_copy(update={"stage_status": "waiting_user"})
                        if command.execution_mode == "manual"
                        else journey
                    )
                    next_session_revision = command.expected_session_revision + 1
                    session_updated = connection.execute(
                        update(AgentCanvasGuidanceSessionRow)
                        .where(
                            AgentCanvasGuidanceSessionRow.session_id == command.session_id,
                            AgentCanvasGuidanceSessionRow.revision
                            == command.expected_session_revision,
                        )
                        .values(
                            journey_state_json=next_journey.model_dump_json(),
                            revision=next_session_revision,
                            updated_at=timestamp,
                        )
                    )
                    if session_updated.rowcount != 1:
                        raise _stale("session_revision")
                    self._fault("guidance")

                    awaiting_id: str | None = None
                    automatic_ids: tuple[str, ...] = ()
                    if command.execution_mode == "manual":
                        awaiting_id = f"awaiting:{checkpoint_id}"
                        connection.execute(
                            insert(AgentCanvasGuidanceAwaitingRow).values(
                                awaiting_id=awaiting_id,
                                workflow_id=command.workflow_id,
                                session_id=command.session_id,
                                checkpoint_id=checkpoint_id,
                                kind="manual_node_run",
                                requires_user_action=True,
                                resume_policy="node_terminal",
                                interaction_id=None,
                                node_ids_json=_dump(
                                    [item.node_id for item in command.preparations]
                                ),
                                stage="storyboard_grids",
                                stage_revision=command.expected_stage_revision,
                                created_at=timestamp,
                            )
                        )
                    else:
                        automatic_ids = tuple(
                            self._automatic_runs.enqueue_in_transaction(
                                connection,
                                workflow_id=command.workflow_id,
                                source_action_id=action_id,
                                node_id=item.node_id,
                                now=now,
                            ).command_id
                            for item in command.preparations
                        )
                    self._fault("awaiting_or_command")

                    next_workflow_revision = command.expected_workflow_revision + 1
                    workflow_updated = connection.execute(
                        update(AgentCanvasWorkflowRow)
                        .where(
                            AgentCanvasWorkflowRow.workflow_id == command.workflow_id,
                            AgentCanvasWorkflowRow.revision == command.expected_workflow_revision,
                        )
                        .values(revision=next_workflow_revision, updated_at=timestamp)
                    )
                    if workflow_updated.rowcount != 1:
                        raise _stale("workflow_revision")

                    turn = (
                        connection.execute(
                            select(AgentCanvasChatTurnRow).where(
                                AgentCanvasChatTurnRow.turn_id == command.action_turn_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if turn is None:
                        raise _invalid("action_turn")
                    if command.execution_mode == "manual":
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=command.workflow_id,
                                node_id=command.preparations[0].node_id,
                                conversation_id=str(turn["conversation_id"]),
                                turn_id=command.action_turn_id,
                                action_id=action_id,
                                event_type="journey_stage_waiting_user",
                                transition_key=f"{action_id}:waiting",
                                created_at=timestamp,
                                payload={
                                    "previous_stage": "storyboard_grids",
                                    "next_stage": "storyboard_grids",
                                    "previous_status": "working",
                                    "next_status": "waiting_user",
                                    "stage_revision": command.expected_stage_revision,
                                    "reason": "runnable_storyboard_draft",
                                    "source_materialization_id": command.materialization_id,
                                    "checkpoint_id": checkpoint_id,
                                },
                            ),
                        )
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=command.workflow_id,
                                node_id=command.preparations[0].node_id,
                                conversation_id=str(turn["conversation_id"]),
                                turn_id=command.action_turn_id,
                                action_id=action_id,
                                event_type="guidance_awaiting_entered",
                                transition_key=f"{action_id}:awaiting",
                                created_at=timestamp,
                                payload={
                                    "awaiting_id": awaiting_id,
                                    "session_id": command.session_id,
                                    "checkpoint_id": checkpoint_id,
                                    "kind": "manual_node_run",
                                    "resume_policy": "node_terminal",
                                    "interaction_id": None,
                                    "node_ids": [item.node_id for item in command.preparations],
                                },
                            ),
                        )
                    self._fault("event")
                    connection.commit()
                    return StoryboardPromptReadyPromotionResultV1(
                        workflow_id=command.workflow_id,
                        materialization_id=command.materialization_id,
                        checkpoint_id=checkpoint_id,
                        workflow_revision=next_workflow_revision,
                        session_revision=next_session_revision,
                        stage_revision=command.expected_stage_revision,
                        awaiting_id=awaiting_id,
                        automatic_run_command_ids=automatic_ids,
                    )
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise V2PersistenceError(
                "storyboard_prompt_ready_authority_invalid",
                "Storyboard prompt-ready promotion could not be persisted.",
                stage="storyboard_prompt_ready_promotion",
                details={"invariant": "persistence"},
            ) from error

    def _materialization(
        self,
        connection,
        command: StoryboardPromptReadyPromotionCommandV1,
    ) -> Mapping[str, object]:
        row = (
            connection.execute(
                select(AgentCanvasMaterializationCommitRow).where(
                    AgentCanvasMaterializationCommitRow.materialization_id
                    == command.materialization_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise _invalid("materialization")
        if (
            str(row["workflow_id"]) != command.workflow_id
            or str(row["action_turn_id"]) != command.action_turn_id
        ):
            raise _invalid("materialization_lineage")
        return row

    @staticmethod
    def _session(connection, command):
        row = (
            connection.execute(
                select(AgentCanvasGuidanceSessionRow).where(
                    AgentCanvasGuidanceSessionRow.session_id == command.session_id,
                    AgentCanvasGuidanceSessionRow.workflow_id == command.workflow_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise _invalid("guidance_session")
        return row

    @staticmethod
    def _validate_materialization_outcome(
        row: Mapping[str, object],
        command: StoryboardPromptReadyPromotionCommandV1,
    ) -> None:
        outcome = MaterializationOutcomeV1.model_validate_json(str(row["outcome_json"]))
        expected_pairs = tuple(zip(outcome.node_ids, outcome.prompt_preparation_ids, strict=True))
        command_pairs = tuple((item.node_id, item.operation_id) for item in command.preparations)
        if tuple(sorted(expected_pairs)) != command_pairs:
            raise _invalid("preparation_lineage")
        document_revisions = {
            item.document_id: item.after_revision for item in outcome.document_results
        }
        if document_revisions.get(command.production_plan_document_id) != (
            command.production_plan_revision
        ):
            raise _invalid("production_plan_lineage")

    @staticmethod
    def _validate_production_plan(connection, command) -> None:
        row = (
            connection.execute(
                select(AgentWorkingDocumentRow).where(
                    AgentWorkingDocumentRow.document_id == command.production_plan_document_id,
                    AgentWorkingDocumentRow.workflow_id == command.workflow_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            row is None
            or str(row["document_kind"]) != "storyboard_production_plan"
            or int(row["revision"]) != command.production_plan_revision
        ):
            raise _invalid("production_plan")
        content = json.loads(str(row["content_json"]))
        planned_nodes = content.get("planned_nodes", [])
        expected_ids = {item.node_id for item in command.preparations}
        if not expected_ids.issubset(
            {
                str(item.get("node_id"))
                for item in planned_nodes
                if isinstance(item, dict)
                and item.get("materialization_id") == command.materialization_id
            }
        ):
            raise _invalid("production_plan_nodes")

    @staticmethod
    def _validate_nodes(connection, command) -> tuple[Mapping[str, object], ...]:
        rows: list[Mapping[str, object]] = []
        for pair in command.preparations:
            row = (
                connection.execute(
                    select(AgentCanvasNodeRow).where(
                        AgentCanvasNodeRow.workflow_id == command.workflow_id,
                        AgentCanvasNodeRow.node_id == pair.node_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None or int(row["revision"]) != pair.expected_node_revision:
                raise _stale("node_revision")
            if (
                str(row["node_type"]) != "image"
                or str(row["creative_role"]) != "storyboard_sequence"
                or str(row["status"]) != "draft"
            ):
                raise _invalid("node_role")
            preparation = NodePromptPreparationV1.model_validate_json(
                str(row["prompt_preparation_json"])
            )
            prompt = str(row["generation_prompt"] or "").strip()
            if (
                preparation.status != "ready"
                or preparation.operation_id != pair.operation_id
                or not prompt
                or preparation.prompt_digest != sha256(prompt.encode("utf-8")).hexdigest()
            ):
                raise _invalid("prompt_ready")
            required = (
                preparation.context_snapshot_id,
                preparation.role_variant,
                preparation.recipe_id,
                preparation.recipe_version,
                preparation.recipe_digest,
                preparation.requirement_revision_id,
                preparation.requirement_revision_no,
                preparation.binding_digest,
                preparation.style_projection_digest,
                preparation.brief_digest,
            )
            if any(value is None or value == "" for value in required):
                raise _invalid("prompt_provenance")
            if preparation.attempt_stage != "completed":
                raise _invalid("prompt_attempt_stage")
            metadata = json.loads(str(row["metadata_json"]))
            if metadata.get("source_agent_document_id") != command.production_plan_document_id:
                raise _invalid("node_plan_lineage")
            expected_metadata = {
                "prompt_context_digest": preparation.context_snapshot_id,
                "prompt_digest": preparation.prompt_digest,
                "prompt_recipe_id": preparation.recipe_id,
                "prompt_recipe_version": preparation.recipe_version,
                "prompt_recipe_digest": preparation.recipe_digest,
                "prompt_reference_bundle_digest": preparation.binding_digest,
                "prompt_style_projection_digest": preparation.style_projection_digest,
            }
            if any(metadata.get(key) != value for key, value in expected_metadata.items()):
                raise _invalid("prompt_provenance")
            connection.execute(
                select(AgentCanvasBindingRow.binding_id).where(
                    AgentCanvasBindingRow.workflow_id == command.workflow_id,
                    AgentCanvasBindingRow.target_node_id == pair.node_id,
                    AgentCanvasBindingRow.enabled.is_(True),
                )
            ).all()
            rows.append(row)
        return tuple(rows)

    @staticmethod
    def _validate_execution_mode(connection, command) -> None:
        mode = connection.execute(
            select(AgentCanvasExecutionSettingsRow.media_execution_mode).where(
                AgentCanvasExecutionSettingsRow.workflow_id == command.workflow_id
            )
        ).scalar_one_or_none()
        if (mode or "manual") != command.execution_mode:
            raise _stale("execution_mode")

    def _replay_result(
        self,
        connection,
        *,
        command: StoryboardPromptReadyPromotionCommandV1,
        session: Mapping[str, object],
        checkpoint_id: str,
        action_id: str,
    ) -> StoryboardPromptReadyPromotionResultV1 | None:
        node_rows = tuple(
            connection.execute(
                select(AgentCanvasNodeRow).where(
                    AgentCanvasNodeRow.workflow_id == command.workflow_id,
                    AgentCanvasNodeRow.node_id == pair.node_id,
                )
            )
            .mappings()
            .one_or_none()
            for pair in command.preparations
        )
        if any(row is None for row in node_rows):
            return None
        if any(
            json.loads(str(row["metadata_json"])).get("guided_checkpoint", {}).get("checkpoint_id")
            != checkpoint_id
            for row in node_rows
        ):
            return None
        journey = GuidedProductionJourneyV1.model_validate_json(str(session["journey_state_json"]))
        awaiting_id: str | None = None
        automatic_ids: tuple[str, ...] = ()
        if command.execution_mode == "manual":
            if journey.stage_status != "waiting_user":
                raise _stale("replay_journey")
            awaiting = (
                connection.execute(
                    select(AgentCanvasGuidanceAwaitingRow).where(
                        AgentCanvasGuidanceAwaitingRow.workflow_id == command.workflow_id,
                        AgentCanvasGuidanceAwaitingRow.checkpoint_id == checkpoint_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if awaiting is None:
                raise _invalid("replay_awaiting")
            awaiting_id = str(awaiting["awaiting_id"])
        else:
            if journey.stage_status != "working":
                raise _stale("replay_journey")
            automatic_ids = tuple(
                str(value)
                for value in connection.execute(
                    select(AgentCanvasAutomaticRunCommandRow.command_id).where(
                        AgentCanvasAutomaticRunCommandRow.workflow_id == command.workflow_id,
                        AgentCanvasAutomaticRunCommandRow.source_action_id == action_id,
                    )
                ).scalars()
            )
            if len(automatic_ids) != len(command.preparations):
                raise _invalid("replay_automatic_command")
        workflow_revision = connection.execute(
            select(AgentCanvasWorkflowRow.revision).where(
                AgentCanvasWorkflowRow.workflow_id == command.workflow_id
            )
        ).scalar_one()
        return StoryboardPromptReadyPromotionResultV1(
            workflow_id=command.workflow_id,
            materialization_id=command.materialization_id,
            checkpoint_id=checkpoint_id,
            workflow_revision=int(workflow_revision),
            session_revision=int(session["revision"]),
            stage_revision=command.expected_stage_revision,
            awaiting_id=awaiting_id,
            automatic_run_command_ids=automatic_ids,
            replayed=True,
        )

    def _fault(self, boundary: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(boundary)


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _stale(invariant: str) -> V2PersistenceError:
    return V2PersistenceError(
        "storyboard_prompt_ready_promotion_stale",
        "Storyboard prompt-ready authority changed before promotion.",
        stage="storyboard_prompt_ready_promotion",
        details={"invariant": invariant},
    )


def _invalid(invariant: str) -> V2PersistenceError:
    return V2PersistenceError(
        "storyboard_prompt_ready_authority_invalid",
        "Storyboard prompt-ready authority is invalid.",
        stage="storyboard_prompt_ready_promotion",
        details={"invariant": invariant},
    )
