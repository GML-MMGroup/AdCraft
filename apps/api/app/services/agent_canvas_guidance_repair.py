"""Audited append-only repair for one explicitly retained guided workflow."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasGuidanceSessionRow,
    WorkflowEventRow,
)
from app.persistence.project_repository import ProjectRepository
from app.schemas.agent_canvas_creative_session import CreativeElementDecisionV2
from app.schemas.agent_canvas_guidance import (
    GuidanceAuthorityRepairPlanV1,
    GuidanceAuthorityRepairReceiptV1,
    GuidanceReadyAssetAssertionV1,
)
from app.schemas.agent_canvas_requirements import RequirementElementPresenceV1
from app.schemas.v2_persistence import V2EventInsert
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repair_error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guidance_authority_repair")
