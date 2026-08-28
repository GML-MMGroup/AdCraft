"""Exact media confirmation authority for guided production."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal, Protocol

from app.persistence.agent_canvas_production_closure_repository import (
    AgentCanvasProductionClosureRepository,
)
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.schemas.agent_canvas import CanvasNodeV2, ProjectAssetSummaryV2
from app.schemas.agent_canvas_production_closure import GuidedMediaConfirmationV1
from app.schemas.v2_persistence import V2EventInsert


ConfirmationActor = Literal["user", "agent"]
Clock = Callable[[], datetime]


class _WorkflowReader(Protocol):
    def get_node(self, workflow_id: str, node_id: str) -> CanvasNodeV2: ...


class _PlanReader(Protocol):
    def list_plans(self, workflow_id: str): ...


class _StoryboardProgression(Protocol):
    def on_node_ready(
        self,
        node: CanvasNodeV2,
        *,
        confirmation: GuidedMediaConfirmationV1,
    ) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class GuidedMediaConfirmationResult:
    confirmation: GuidedMediaConfirmationV1
    created_node_ids: tuple[str, ...] = ()


class GuidedMediaConfirmationService:
    """Confirm one exact current media result without transferring acceptance."""

    def __init__(
        self,
        *,
        workflows: _WorkflowReader,
        plans: _PlanReader,
        assets: Callable[[str], ProjectAssetSummaryV2],
        asset_readable: Callable[[ProjectAssetSummaryV2], bool],
        receipts: AgentCanvasProductionClosureRepository,
        events: EventRepository,
        progression: _StoryboardProgression | None = None,
        clock: Clock = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._workflows = workflows
        self._plans = plans
        self._assets = assets
        self._asset_readable = asset_readable
        self._receipts = receipts
        self._events = events
        self._progression = progression
        self._clock = clock

    def confirm(
        self,
        *,
        workflow_id: str,
        plan_document_id: str,
        expected_plan_revision: int,
        node_id: str,
        expected_node_revision: int,
        asset_id: str,
        asset_version_id: str,
        accepted_by: ConfirmationActor,
        action_id: str,
        decision_id: str,
    ) -> GuidedMediaConfirmationV1:
        return self.confirm_result(
            workflow_id=workflow_id,
            plan_document_id=plan_document_id,
            expected_plan_revision=expected_plan_revision,
            node_id=node_id,
            expected_node_revision=expected_node_revision,
            asset_id=asset_id,
            asset_version_id=asset_version_id,
            accepted_by=accepted_by,
            action_id=action_id,
            decision_id=decision_id,
        ).confirmation

    def confirm_result(
        self,
        *,
        workflow_id: str,
        plan_document_id: str,
        expected_plan_revision: int,
        node_id: str,
        expected_node_revision: int,
        asset_id: str,
        asset_version_id: str,
        accepted_by: ConfirmationActor,
        action_id: str,
        decision_id: str,
    ) -> GuidedMediaConfirmationResult:
        plan = next(
            (
                item
                for item in self._plans.list_plans(workflow_id).items
                if item.document_id == plan_document_id
            ),
            None,
        )
        if plan is None:
            raise _error(
                "guided_media_confirmation_stale",
                "Storyboard Plan is not current for media confirmation.",
            )
        records = tuple(
            getattr(plan.content, "planned_nodes", None)
            or getattr(plan.content, "node_records", ())
        )
        record = next((item for item in records if item.node_id == node_id), None)
        if record is None:
            raise _error(
                "guided_media_confirmation_stale",
                "Media Node is not part of the current Storyboard Plan.",
            )
        node = self._workflows.get_node(workflow_id, node_id)
        try:
            asset = self._assets(asset_id)
        except (KeyError, LookupError, V2PersistenceError) as error:
            raise _error(
                "guided_media_confirmation_stale",
                "Media Asset is not current for confirmation.",
            ) from error
        media_role = _media_role(record.node_role)
        if (
            plan.revision != expected_plan_revision
            or node.revision != expected_node_revision
            or node.status != "ready"
            or node.output_asset_id != asset_id
            or asset.status != "ready"
            or asset.media_type != media_role
            or asset.version_id != asset_version_id
        ):
            raise _error(
                "guided_media_confirmation_stale",
                "Media confirmation does not match current Plan, Node, and Asset authority.",
            )
        if not self._asset_readable(asset):
            raise _error(
                "guided_media_asset_unreadable",
                "Media Asset bytes are not readable through canonical storage.",
            )

        logical_identity = ":".join(
            (
                plan.document_id,
                str(plan.revision),
                node.node_id,
                str(node.revision),
                asset.version_id or "",
            )
        )
        confirmation_id = "confirmation_" + sha256(logical_identity.encode()).hexdigest()[:32]
        confirmation: GuidedMediaConfirmationV1 | None = None
        try:
            confirmation = self._receipts.get_confirmation(confirmation_id)
        except V2PersistenceError as error:
            if error.code != "guided_production_receipt_not_found":
                raise

        created = confirmation is None
        if confirmation is None:
            confirmation = self._receipts.save_confirmation(
                GuidedMediaConfirmationV1(
                    confirmation_id=confirmation_id,
                    logical_identity=logical_identity,
                    workflow_id=workflow_id,
                    plan_document_id=plan.document_id,
                    plan_revision=plan.revision,
                    media_role=media_role,
                    sequence_id=record.sequence_id,
                    node_id=node.node_id,
                    node_revision=node.revision,
                    asset_id=asset.asset_id,
                    asset_version_id=asset.version_id or "",
                    asset_digest=asset.checksum,
                    accepted_by=accepted_by,
                    action_id=action_id,
                    decision_id=decision_id,
                    confirmed_at=self._clock(),
                )
            )
        if created:
            self._events.append(
                V2EventInsert(
                    workflow_id=workflow_id,
                    node_id=node.node_id,
                    event_type="guided_media_confirmed",
                    transition_key=f"guided-media-confirmed:{confirmation.confirmation_id}",
                    action_id=action_id,
                    created_at=confirmation.confirmed_at.isoformat(),
                    payload={
                        "confirmation_id": confirmation.confirmation_id,
                        "plan_document_id": confirmation.plan_document_id,
                        "plan_revision": confirmation.plan_revision,
                        "node_revision": confirmation.node_revision,
                        "asset_id": confirmation.asset_id,
                        "asset_version_id": confirmation.asset_version_id,
                        "asset_digest": confirmation.asset_digest,
                        "accepted_by": confirmation.accepted_by,
                        "sequence_id": confirmation.sequence_id,
                        "media_role": confirmation.media_role,
                    },
                )
            )
        created_node_ids: tuple[str, ...] = ()
        if (
            self._progression is not None
            and record.node_role == "storyboard_grid"
            and record.sequence_id == _first_sequence_id(plan.content.segments)
        ):
            created_node_ids = self._progression.on_node_ready(
                node,
                confirmation=confirmation,
            )
        return GuidedMediaConfirmationResult(
            confirmation=confirmation,
            created_node_ids=created_node_ids,
        )


def _first_sequence_id(segments: tuple[object, ...]) -> str:
    sequence = next((item for item in segments if getattr(item, "order", None) == 1), None)
    if sequence is None:
        raise V2PersistenceError(
            "guided_media_confirmation_stale",
            "The Storyboard Plan has no explicitly ordered first sequence.",
            stage="guided_media_confirmation",
        )
    return str(sequence.sequence_id)


def _media_role(node_role: str) -> Literal["image", "video", "audio"]:
    roles = {
        "storyboard_grid": "image",
        "video_segment": "video",
        "bgm": "audio",
    }
    try:
        return roles[node_role]
    except KeyError as error:
        raise _error(
            "guided_media_confirmation_stale",
            "The current Plan record is not confirmable media.",
        ) from error


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guided_media_confirmation")
