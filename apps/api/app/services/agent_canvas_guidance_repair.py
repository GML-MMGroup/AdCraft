"""Audited append-only repair for one explicitly retained guided workflow."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
    canonical_requirement_ledger,
)
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasChatTurnRow,
    AgentCanvasContinuationOutboxRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasGuidanceTopicRow,
    AgentCanvasWorkflowRow,
    WorkflowEventRow,
)
from app.persistence.project_repository import ProjectRepository
from app.schemas.agent_canvas_creative_session import CreativeElementDecisionV2
from app.schemas.agent_canvas_guidance import (
    GuidanceAuthorityRepairPlanV1,
    GuidanceAuthorityRepairReceiptV1,
    GuidanceReadyAssetAssertionV1,
    GuidanceRequirementLedgerRepairPlanV1,
    GuidanceRequirementLedgerRepairReceiptV1,
    GuidanceRequirementLedgerRepairRuntimeAssertionV1,
)
from app.services.agent_canvas_production_journey import parse_production_journey
from app.schemas.agent_canvas_requirements import RequirementElementPresenceV1
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_requirement_directives import (
    canonicalize_requirement_directives,
)
from app.services.v2_storage_adapter import StorageAdapter


RETAINED_GUIDANCE_REPAIR_WORKFLOW_IDS = frozenset({"adwf_v2_d5a7f295b7731c25"})
_ELEMENT_KINDS = (
    "audio",
    "character",
    "product",
    "prop",
    "scene",
    "script",
    "storyboard",
    "video",
    "world_setting",
)


class GuidanceAuthorityForwardRepairService:
    """Plan and apply one checksum-guarded, append-only authority repair."""

    def __init__(
        self,
        database: V2Database,
        data_dir: Path,
        *,
        allowed_workflow_ids: frozenset[str] = RETAINED_GUIDANCE_REPAIR_WORKFLOW_IDS,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._database = database
        self._data_dir = data_dir
        self._allowed_workflow_ids = allowed_workflow_ids
        self._events = EventRepository(database)
        self._workflows = AgentCanvasWorkflowRepository(
            database, ProjectRepository(database), self._events
        )
        self._conversations = AgentCanvasConversationRepository(database, self._events)
        self._requirements = AgentCanvasRequirementRepository(database)
        self._assets = V2AssetLibraryRepository(database)
        self._storage = StorageAdapter(data_dir)
        self._fault_injector = fault_injector

    def plan_requirement_ledger_repair(
        self,
        *,
        workflow_id: str,
        expected_workflow_revision: int,
        expected_requirement_revision_id: str,
        expected_requirement_digest: str,
        expected_session_revision: int,
        expected_journey_stage_revision: int,
        stale_turn_id: str,
        stale_continuation_id: str,
        obsolete_directive_ids: tuple[str, ...],
        selected_topic_ids: tuple[str, ...],
        ready_assets: tuple[GuidanceReadyAssetAssertionV1, ...],
    ) -> GuidanceRequirementLedgerRepairPlanV1:
        self._validate_allowlist(workflow_id)
        with self._database.engine.connect() as connection:
            return self._build_requirement_ledger_repair_plan(
                connection,
                workflow_id=workflow_id,
                expected_workflow_revision=expected_workflow_revision,
                expected_requirement_revision_id=expected_requirement_revision_id,
                expected_requirement_digest=expected_requirement_digest,
                expected_session_revision=expected_session_revision,
                expected_journey_stage_revision=expected_journey_stage_revision,
                stale_turn_id=stale_turn_id,
                stale_continuation_id=stale_continuation_id,
                obsolete_directive_ids=obsolete_directive_ids,
                selected_topic_ids=selected_topic_ids,
                ready_assets=ready_assets,
            )

    def apply_requirement_ledger_repair(
        self,
        plan: GuidanceRequirementLedgerRepairPlanV1,
    ) -> GuidanceRequirementLedgerRepairReceiptV1:
        self._validate_allowlist(plan.workflow_id)
        transition_key = f"guidance-requirement-ledger-repair:{plan.plan_digest}"
        with self._database.engine.connect() as connection:
            replay = _event_by_transition_key(connection, transition_key)
            if replay is not None:
                return _requirement_receipt_from_event(replay, replayed=True)
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                replay = _event_by_transition_key(connection, transition_key)
                if replay is not None:
                    connection.commit()
                    return _requirement_receipt_from_event(replay, replayed=True)
                current_plan = self._build_requirement_ledger_repair_plan(
                    connection,
                    workflow_id=plan.workflow_id,
                    expected_workflow_revision=plan.expected_workflow_revision,
                    expected_requirement_revision_id=plan.before_requirement_revision_id,
                    expected_requirement_digest=plan.before_requirement_digest,
                    expected_session_revision=plan.expected_session_revision,
                    expected_journey_stage_revision=plan.expected_journey_stage_revision,
                    stale_turn_id=plan.runtime.stale_turn_id,
                    stale_continuation_id=plan.runtime.stale_continuation_id,
                    obsolete_directive_ids=plan.obsolete_directive_ids,
                    selected_topic_ids=plan.selected_topic_ids,
                    ready_assets=plan.ready_assets,
                )
                if current_plan != plan:
                    raise _repair_error(
                        "guidance_repair_state_stale",
                        "Requirement repair authority changed before apply.",
                    )
                current = self._requirements.get_current_in_transaction(
                    connection,
                    plan.workflow_id,
                )
                obsolete = set(plan.obsolete_directive_ids)
                remaining = tuple(
                    item
                    for item in current.ledger.active_directives
                    if item.directive_id not in obsolete
                )
                canonical = canonicalize_requirement_directives(remaining)
                appended = self._requirements.append_in_transaction(
                    connection,
                    workflow_id=plan.workflow_id,
                    expected_revision_no=current.revision_no,
                    next_ledger=current.ledger.model_copy(
                        update={"active_directives": canonical.active_directives}
                    ),
                    source_kind="manual_edit",
                    created_at=datetime.now(timezone.utc),
                )
                if appended.revision_id == current.revision_id:
                    raise _repair_error(
                        "guidance_repair_state_stale",
                        "Requirement repair does not produce a forward revision.",
                    )
                self._inject_fault("requirement")
                now = datetime.now(timezone.utc)
                if self._terminalize_repair_turn(connection, plan, now) != 1:
                    raise _repair_error(
                        "guidance_repair_state_stale",
                        "Stale Turn changed before repair apply.",
                    )
                self._inject_fault("turn")
                if self._terminalize_repair_continuation(connection, plan, now) != 1:
                    raise _repair_error(
                        "guidance_repair_state_stale",
                        "Stale Continuation changed before repair apply.",
                    )
                self._inject_fault("continuation")
                self._append_repair_terminal_events(connection, plan, transition_key, now)
                receipt_payload = {
                    "workflow_id": plan.workflow_id,
                    "plan_digest": plan.plan_digest,
                    "before_requirement_revision_id": current.revision_id,
                    "before_requirement_digest": current.digest,
                    "after_requirement_revision_id": appended.revision_id,
                    "after_requirement_revision_no": appended.revision_no,
                    "after_requirement_digest": appended.digest,
                    "removed_directive_ids": sorted(
                        {*plan.obsolete_directive_ids, *plan.duplicate_directive_ids}
                    ),
                    "retained_directive_ids": plan.retained_directive_ids,
                    "terminalized_turn_id": plan.runtime.stale_turn_id,
                    "terminalized_continuation_id": plan.runtime.stale_continuation_id,
                    "ready_asset_set_digest": plan.ready_asset_set_digest,
                    "applied_at": now.isoformat(),
                    "replayed": False,
                }
                event = self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=plan.workflow_id,
                        event_type="guidance_requirement_ledger_repaired",
                        transition_key=transition_key,
                        created_at=now.isoformat(),
                        payload=receipt_payload,
                    ),
                )
                self._inject_fault("event")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return GuidanceRequirementLedgerRepairReceiptV1.model_validate(
            {**receipt_payload, "event_id": f"event:{event.seq}"}
        )

    def _terminalize_repair_turn(
        self,
        connection,
        plan: GuidanceRequirementLedgerRepairPlanV1,
        now: datetime,
    ) -> int:
        runtime = plan.runtime
        result = connection.execute(
            update(AgentCanvasChatTurnRow)
            .where(
                AgentCanvasChatTurnRow.turn_id == runtime.stale_turn_id,
                AgentCanvasChatTurnRow.workflow_id == plan.workflow_id,
                AgentCanvasChatTurnRow.status == runtime.turn_status,
                AgentCanvasChatTurnRow.operation_stage == runtime.turn_operation_stage,
                AgentCanvasChatTurnRow.error_code == runtime.turn_error_code,
                AgentCanvasChatTurnRow.error_message == runtime.turn_error_message,
            )
            .values(status="failed", retryable=False, updated_at=now.isoformat())
        )
        return result.rowcount

    def _terminalize_repair_continuation(
        self,
        connection,
        plan: GuidanceRequirementLedgerRepairPlanV1,
        now: datetime,
    ) -> int:
        runtime = plan.runtime
        result = connection.execute(
            update(AgentCanvasContinuationOutboxRow)
            .where(
                AgentCanvasContinuationOutboxRow.continuation_id == runtime.stale_continuation_id,
                AgentCanvasContinuationOutboxRow.workflow_id == plan.workflow_id,
                AgentCanvasContinuationOutboxRow.status == runtime.continuation_status,
                AgentCanvasContinuationOutboxRow.attempt_count
                == runtime.continuation_attempt_count,
                AgentCanvasContinuationOutboxRow.lease_generation
                == runtime.continuation_lease_generation,
                AgentCanvasContinuationOutboxRow.last_error_code == runtime.continuation_error_code,
                AgentCanvasContinuationOutboxRow.last_error_message
                == runtime.continuation_error_message,
            )
            .values(
                status="failed",
                lease_owner=None,
                lease_expires_at=None,
                updated_at=now.isoformat(),
            )
        )
        return result.rowcount

    def _append_repair_terminal_events(
        self,
        connection,
        plan: GuidanceRequirementLedgerRepairPlanV1,
        transition_key: str,
        now: datetime,
    ) -> None:
        for event_type, identity_key, identity in (
            ("agent_turn_failed", "turn_id", plan.runtime.stale_turn_id),
            (
                "continuation_failed",
                "continuation_id",
                plan.runtime.stale_continuation_id,
            ),
        ):
            self._events.append_in_transaction(
                connection,
                V2EventInsert(
                    workflow_id=plan.workflow_id,
                    turn_id=plan.runtime.stale_turn_id,
                    event_type=event_type,
                    transition_key=f"{transition_key}:{event_type}",
                    created_at=now.isoformat(),
                    payload={
                        identity_key: identity,
                        "error_code": plan.repair_error_code,
                        "retryable": False,
                    },
                ),
            )

    def _inject_fault(self, boundary: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(boundary)

    def _build_requirement_ledger_repair_plan(
        self,
        connection,
        *,
        workflow_id: str,
        expected_workflow_revision: int,
        expected_requirement_revision_id: str,
        expected_requirement_digest: str,
        expected_session_revision: int,
        expected_journey_stage_revision: int,
        stale_turn_id: str,
        stale_continuation_id: str,
        obsolete_directive_ids: tuple[str, ...],
        selected_topic_ids: tuple[str, ...],
        ready_assets: tuple[GuidanceReadyAssetAssertionV1, ...],
    ) -> GuidanceRequirementLedgerRepairPlanV1:
        workflow = (
            connection.execute(
                select(AgentCanvasWorkflowRow).where(
                    AgentCanvasWorkflowRow.workflow_id == workflow_id
                )
            )
            .mappings()
            .one_or_none()
        )
        current = self._requirements.get_current_in_transaction(connection, workflow_id)
        session = (
            connection.execute(
                select(AgentCanvasGuidanceSessionRow).where(
                    AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if workflow is None or session is None:
            raise _repair_error(
                "guidance_repair_state_stale",
                "Requirement repair authority is unavailable.",
            )
        journey = parse_production_journey(str(session["journey_state_json"]))
        selected_topics = tuple(
            sorted(
                connection.execute(
                    select(AgentCanvasGuidanceTopicRow.topic_id).where(
                        AgentCanvasGuidanceTopicRow.session_id == session["session_id"],
                        AgentCanvasGuidanceTopicRow.status == "selected",
                    )
                ).scalars()
            )
        )
        if (
            workflow["revision"] != expected_workflow_revision
            or current.revision_id != expected_requirement_revision_id
            or current.digest != expected_requirement_digest
            or session["revision"] != expected_session_revision
            or journey.stage_revision != expected_journey_stage_revision
            or selected_topics != tuple(sorted(selected_topic_ids))
        ):
            raise _repair_error(
                "guidance_repair_state_stale",
                "Requirement repair authority does not match current state.",
            )
        turn = (
            connection.execute(
                select(AgentCanvasChatTurnRow).where(
                    AgentCanvasChatTurnRow.turn_id == stale_turn_id,
                    AgentCanvasChatTurnRow.workflow_id == workflow_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        continuation = (
            connection.execute(
                select(AgentCanvasContinuationOutboxRow).where(
                    AgentCanvasContinuationOutboxRow.continuation_id == stale_continuation_id,
                    AgentCanvasContinuationOutboxRow.workflow_id == workflow_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if not _repair_runtime_is_expected(turn, continuation):
            raise _repair_error(
                "guidance_repair_state_stale",
                "Named stale runtime does not match the repair contract.",
            )
        obsolete = tuple(sorted(set(obsolete_directive_ids)))
        active_ids = {item.directive_id for item in current.ledger.active_directives}
        if not obsolete or not set(obsolete).issubset(active_ids):
            raise _repair_error(
                "guidance_repair_state_stale",
                "Obsolete Requirement directives do not match current state.",
            )
        remaining = tuple(
            item
            for item in current.ledger.active_directives
            if item.directive_id not in set(obsolete)
        )
        canonical = canonicalize_requirement_directives(remaining)
        repaired_ledger = current.ledger.model_copy(
            update={"active_directives": canonical.active_directives}
        )
        _, after_digest = canonical_requirement_ledger(repaired_ledger)
        sorted_assets = tuple(
            sorted(ready_assets, key=lambda item: (item.asset_id, item.asset_version_id))
        )
        self._validate_ready_assets_in_transaction(connection, sorted_assets)
        runtime = GuidanceRequirementLedgerRepairRuntimeAssertionV1(
            stale_turn_id=turn["turn_id"],
            turn_status=turn["status"],
            turn_operation_stage=turn["operation_stage"],
            turn_error_code=turn["error_code"],
            turn_error_message=turn["error_message"],
            stale_continuation_id=continuation["continuation_id"],
            continuation_status=continuation["status"],
            continuation_attempt_count=continuation["attempt_count"],
            continuation_lease_generation=continuation["lease_generation"],
            continuation_error_code=continuation["last_error_code"],
            continuation_error_message=continuation["last_error_message"],
        )
        payload = {
            "workflow_id": workflow_id,
            "expected_workflow_revision": workflow["revision"],
            "before_requirement_revision_id": current.revision_id,
            "before_requirement_revision_no": current.revision_no,
            "before_requirement_digest": current.digest,
            "before_directive_set_digest": _json_digest(
                [item.model_dump(mode="json") for item in current.ledger.active_directives]
            ),
            "expected_session_revision": session["revision"],
            "expected_journey_stage_revision": journey.stage_revision,
            "selected_topic_ids": selected_topics,
            "obsolete_directive_ids": obsolete,
            "duplicate_directive_ids": canonical.duplicate_directive_ids,
            "retained_directive_ids": tuple(
                item.directive_id for item in canonical.active_directives
            ),
            "representative_directive_ids": tuple(
                item.directive_id for item in canonical.active_directives
            ),
            "runtime": runtime.model_dump(mode="json"),
            "ready_assets": [item.model_dump(mode="json") for item in sorted_assets],
            "ready_asset_set_digest": _json_digest(
                [item.model_dump(mode="json") for item in sorted_assets]
            ),
            "after_requirement_digest": after_digest,
            "repair_error_code": "requirement_projection_budget_exceeded",
            "repair_error_message": turn["error_message"],
        }
        return GuidanceRequirementLedgerRepairPlanV1.model_validate(
            {**payload, "plan_digest": f"sha256:{_json_digest(payload)}"}
        )

    def _validate_ready_assets_in_transaction(
        self,
        connection,
        ready_assets: tuple[GuidanceReadyAssetAssertionV1, ...],
    ) -> None:
        if len(ready_assets) != 6:
            raise _repair_error(
                "guidance_repair_asset_invalid",
                "Exactly six Ready Assets are required.",
            )
        for assertion in ready_assets:
            version = self._assets.find_version(
                version_id=assertion.asset_version_id,
                connection=connection,
            )
            if (
                version is None
                or version.asset_id != assertion.asset_id
                or version.status != "ready"
                or version.storage_key != assertion.local_path
                or version.size_bytes != assertion.size_bytes
                or version.sha256 != assertion.sha256
            ):
                raise _repair_error(
                    "guidance_repair_asset_invalid",
                    "Ready Asset assertion is stale.",
                )
            path = self._storage.resolve_local_path(version.storage_key)
            if (
                not path.is_file()
                or path.stat().st_size != assertion.size_bytes
                or _sha256(path) != assertion.sha256
            ):
                raise _repair_error(
                    "guidance_repair_asset_invalid",
                    "Ready Asset bytes do not match.",
                )

    def plan(
        self,
        *,
        workflow_id: str,
        expected_workflow_revision: int,
        expected_requirement_revision_id: str,
        expected_session_revision: int,
        expected_journey_stage_revision: int,
        selected_topic_ids: tuple[str, ...],
        ready_assets: tuple[GuidanceReadyAssetAssertionV1, ...],
    ) -> GuidanceAuthorityRepairPlanV1:
        self._validate_allowlist(workflow_id)
        self._validate_authority(
            workflow_id=workflow_id,
            expected_workflow_revision=expected_workflow_revision,
            expected_requirement_revision_id=expected_requirement_revision_id,
            expected_session_revision=expected_session_revision,
            expected_journey_stage_revision=expected_journey_stage_revision,
            selected_topic_ids=selected_topic_ids,
            ready_assets=ready_assets,
        )
        payload = {
            "workflow_id": workflow_id,
            "expected_workflow_revision": expected_workflow_revision,
            "expected_requirement_revision_id": expected_requirement_revision_id,
            "expected_session_revision": expected_session_revision,
            "expected_journey_stage_revision": expected_journey_stage_revision,
            "selected_topic_ids": selected_topic_ids,
            "ready_assets": [item.model_dump(mode="json") for item in ready_assets],
            "intended_element_decisions": {kind: "include" for kind in _ELEMENT_KINDS},
        }
        digest = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
        return GuidanceAuthorityRepairPlanV1.model_validate(
            {**payload, "plan_digest": f"sha256:{digest}"}
        )

    def apply(self, plan: GuidanceAuthorityRepairPlanV1) -> GuidanceAuthorityRepairReceiptV1:
        self._validate_allowlist(plan.workflow_id)
        transition_key = f"guidance-authority-repair:{plan.plan_digest}"
        with self._database.engine.connect() as connection:
            replay = (
                connection.execute(
                    select(WorkflowEventRow).where(
                        WorkflowEventRow.transition_key == transition_key
                    )
                )
                .mappings()
                .one_or_none()
            )
        if replay is not None:
            payload = json.loads(str(replay["payload_json"]))
            if str(replay["workflow_id"]) != plan.workflow_id:
                raise _repair_error("guidance_repair_plan_stale", "Repair plan identity conflicts.")
            return GuidanceAuthorityRepairReceiptV1(
                workflow_id=plan.workflow_id,
                plan_digest=plan.plan_digest,
                appended_requirement_revision_id=str(payload["after_revision_id"]),
                resulting_session_revision=int(payload["resulting_session_revision"]),
                event_id=f"event:{replay['id']}",
                applied_at=str(replay["created_at"]),
                replayed=True,
            )
        expected = self.plan(
            workflow_id=plan.workflow_id,
            expected_workflow_revision=plan.expected_workflow_revision,
            expected_requirement_revision_id=plan.expected_requirement_revision_id,
            expected_session_revision=plan.expected_session_revision,
            expected_journey_stage_revision=plan.expected_journey_stage_revision,
            selected_topic_ids=plan.selected_topic_ids,
            ready_assets=plan.ready_assets,
        )
        if expected.plan_digest != plan.plan_digest:
            raise _repair_error("guidance_repair_plan_stale", "Repair plan digest is stale.")

        now = datetime.now(timezone.utc)
        with self._database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                existing = (
                    connection.execute(
                        select(WorkflowEventRow).where(
                            WorkflowEventRow.transition_key == transition_key
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    payload = json.loads(str(existing["payload_json"]))
                    connection.commit()
                    return GuidanceAuthorityRepairReceiptV1(
                        workflow_id=plan.workflow_id,
                        plan_digest=plan.plan_digest,
                        appended_requirement_revision_id=str(payload["after_revision_id"]),
                        resulting_session_revision=int(payload["resulting_session_revision"]),
                        event_id=f"event:{existing['id']}",
                        applied_at=str(existing["created_at"]),
                        replayed=True,
                    )

                current = self._requirements.get_current_in_transaction(
                    connection, plan.workflow_id
                )
                session_row = (
                    connection.execute(
                        select(AgentCanvasGuidanceSessionRow).where(
                            AgentCanvasGuidanceSessionRow.workflow_id == plan.workflow_id
                        )
                    )
                    .mappings()
                    .one()
                )
                if (
                    current.revision_id != plan.expected_requirement_revision_id
                    or int(session_row["revision"]) != plan.expected_session_revision
                ):
                    raise _repair_error(
                        "guidance_repair_state_stale", "Repair authority changed before apply."
                    )

                revision_no = current.revision_no + 1
                repaired_presence = tuple(
                    RequirementElementPresenceV1(
                        element_kind=kind,
                        presence="include",
                        source_kind="manual_edit",
                        source_text="Authorized retained guidance authority repair.",
                        created_revision_no=revision_no,
                    )
                    for kind in _ELEMENT_KINDS
                )
                repaired_ledger = current.ledger.model_copy(
                    update={"element_presence": repaired_presence}
                )
                appended = self._requirements.append_in_transaction(
                    connection,
                    workflow_id=plan.workflow_id,
                    expected_revision_no=current.revision_no,
                    next_ledger=repaired_ledger,
                    source_kind="manual_edit",
                    created_at=now,
                )

                current_decisions = {
                    item.element_kind: item
                    for item in json.loads(str(session_row["element_decisions_json"]))
                    for item in (CreativeElementDecisionV2.model_validate(item),)
                }
                repaired_decisions = tuple(
                    current_decisions.get(
                        kind,
                        CreativeElementDecisionV2(
                            element_kind=kind,
                            presence="include",
                            authority="user",
                            source="explicit_user",
                        ),
                    ).model_copy(update={"presence": "include"})
                    for kind in _ELEMENT_KINDS
                )
                next_session_revision = plan.expected_session_revision + 1
                changed = connection.execute(
                    update(AgentCanvasGuidanceSessionRow)
                    .where(
                        AgentCanvasGuidanceSessionRow.workflow_id == plan.workflow_id,
                        AgentCanvasGuidanceSessionRow.revision == plan.expected_session_revision,
                    )
                    .values(
                        element_decisions_json=_canonical(
                            [item.model_dump(mode="json") for item in repaired_decisions]
                        ),
                        revision=next_session_revision,
                        updated_at=now.isoformat(),
                    )
                )
                if changed.rowcount != 1:
                    raise _repair_error(
                        "guidance_repair_state_stale", "Repair authority changed before apply."
                    )
                event = self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=plan.workflow_id,
                        event_type="guidance_authority_repaired",
                        transition_key=transition_key,
                        created_at=now.isoformat(),
                        payload={
                            "before_revision_id": current.revision_id,
                            "after_revision_id": appended.revision_id,
                            "resulting_session_revision": next_session_revision,
                            "plan_digest": plan.plan_digest,
                        },
                    ),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return GuidanceAuthorityRepairReceiptV1(
            workflow_id=plan.workflow_id,
            plan_digest=plan.plan_digest,
            appended_requirement_revision_id=appended.revision_id,
            resulting_session_revision=next_session_revision,
            event_id=f"event:{event.seq}",
            applied_at=now,
            replayed=False,
        )

    def _validate_allowlist(self, workflow_id: str) -> None:
        if workflow_id not in self._allowed_workflow_ids:
            raise _repair_error(
                "guidance_repair_workflow_not_allowed",
                "Workflow is not allowlisted for guidance authority repair.",
            )

    def _validate_authority(
        self,
        *,
        workflow_id: str,
        expected_workflow_revision: int,
        expected_requirement_revision_id: str,
        expected_session_revision: int,
        expected_journey_stage_revision: int,
        selected_topic_ids: tuple[str, ...],
        ready_assets: tuple[GuidanceReadyAssetAssertionV1, ...],
    ) -> None:
        workflow = self._workflows.get_workflow(workflow_id)
        requirements = self._requirements.get_current(workflow_id)
        session = self._conversations.get_guidance_session(workflow_id)
        actual_topics = tuple(
            sorted(item.topic_id for item in session.topics if item.status == "selected")
        )
        if (
            workflow.revision != expected_workflow_revision
            or requirements.revision_id != expected_requirement_revision_id
            or session.revision != expected_session_revision
            or session.journey.stage_revision != expected_journey_stage_revision
            or actual_topics != tuple(sorted(selected_topic_ids))
        ):
            raise _repair_error(
                "guidance_repair_state_stale", "Repair authority does not match current state."
            )
        if len(ready_assets) != 6:
            raise _repair_error(
                "guidance_repair_asset_invalid", "Exactly six Ready Assets are required."
            )
        for assertion in ready_assets:
            version = self._assets.find_version(version_id=assertion.asset_version_id)
            if (
                version is None
                or version.asset_id != assertion.asset_id
                or version.status != "ready"
                or version.storage_key != assertion.local_path
                or version.size_bytes != assertion.size_bytes
                or version.sha256 != assertion.sha256
            ):
                raise _repair_error(
                    "guidance_repair_asset_invalid", "Ready Asset assertion is stale."
                )
            path = self._storage.resolve_local_path(version.storage_key)
            if (
                not path.is_file()
                or path.stat().st_size != assertion.size_bytes
                or _sha256(path) != assertion.sha256
            ):
                raise _repair_error(
                    "guidance_repair_asset_invalid", "Ready Asset bytes do not match."
                )


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _json_digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _event_by_transition_key(connection, transition_key: str):
    return (
        connection.execute(
            select(WorkflowEventRow).where(WorkflowEventRow.transition_key == transition_key)
        )
        .mappings()
        .one_or_none()
    )


def _requirement_receipt_from_event(
    event,
    *,
    replayed: bool,
) -> GuidanceRequirementLedgerRepairReceiptV1:
    payload = json.loads(str(event["payload_json"]))
    payload = {
        key: value
        for key, value in payload.items()
        if key in GuidanceRequirementLedgerRepairReceiptV1.model_fields
    }
    return GuidanceRequirementLedgerRepairReceiptV1.model_validate(
        {
            **payload,
            "event_id": f"event:{event['id']}",
            "applied_at": str(event["created_at"]),
            "replayed": replayed,
        }
    )


def _repair_runtime_is_expected(turn, continuation) -> bool:
    return bool(
        turn is not None
        and continuation is not None
        and turn["status"] == "running"
        and continuation["status"] == "retry_wait"
        and turn["operation_stage"]
        and turn["error_code"]
        and turn["error_message"]
        and continuation["last_error_code"]
        and continuation["last_error_message"]
        and turn["error_code"] == continuation["last_error_code"]
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repair_error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guidance_authority_repair")
