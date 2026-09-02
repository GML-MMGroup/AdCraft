"""Strict read-only closure gate for guided production."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Protocol

from app.persistence.agent_canvas_production_closure_repository import (
    AgentCanvasProductionClosureRepository,
)
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.schemas.agent_canvas import CanvasNodeV2, ProjectAssetSummaryV2
from app.schemas.agent_canvas_production_closure import (
    GuidedClosureBlockerV1,
    GuidedClosureInputV1,
    GuidedClosurePlanV1,
    GuidedMediaConfirmationV1,
)
from app.schemas.v2_persistence import V2EventInsert


Clock = Callable[[], datetime]


class _WorkflowReader(Protocol):
    def get_workflow(self, workflow_id: str): ...


class _DocumentReader(Protocol):
    def get_document(self, workflow_id: str, document_id: str): ...


class GuidedProductionClosureService:
    """Freeze exact current guided media or return deterministic blockers."""

    def __init__(
        self,
        *,
        workflows: _WorkflowReader,
        documents: _DocumentReader,
        assets: Callable[[str], ProjectAssetSummaryV2],
        asset_readable: Callable[[ProjectAssetSummaryV2], bool],
        receipts: AgentCanvasProductionClosureRepository,
        has_active_work: Callable[[str, tuple[str, ...]], bool],
        events: EventRepository,
        clock: Clock = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._workflows = workflows
        self._documents = documents
        self._assets = assets
        self._asset_readable = asset_readable
        self._receipts = receipts
        self._has_active_work = has_active_work
        self._events = events
        self._clock = clock

    def freeze(
        self,
        workflow_id: str,
        plan_document_id: str,
        *,
        expected_plan_revision: int,
    ) -> GuidedClosurePlanV1:
        document = self._documents.get_document(workflow_id, plan_document_id)
        if (
            document.kind != "storyboard_production_plan"
            or document.revision != expected_plan_revision
        ):
            raise _error(
                "guided_closure_plan_stale",
                "Guided closure requires the current Storyboard Plan revision.",
            )
        content = document.content
        records = tuple(
            getattr(content, "planned_nodes", None) or getattr(content, "node_records", ())
        )
        exclusions = tuple(getattr(content, "excluded_media", ()))
        nodes = {node.node_id: node for node in self._workflows.get_workflow(workflow_id).nodes}
        planned: list[tuple[object | None, str, int, str]] = []
        for index, sequence in enumerate(content.segments):
            if any(
                item.node_role == "video_segment" and item.sequence_id == sequence.sequence_id
                for item in exclusions
            ):
                continue
            record = next(
                (
                    item
                    for item in records
                    if item.node_role == "video_segment"
                    and item.sequence_id == sequence.sequence_id
                ),
                None,
            )
            planned.append((record, "video", index, sequence.sequence_id))
        bgm_excluded = any(item.node_role == "bgm" for item in exclusions)
        bgm = next((item for item in records if item.node_role == "bgm"), None)
        if bgm is not None and not bgm_excluded:
            planned.append((bgm, "audio", len(planned), ""))

        confirmations = self._receipts.list_confirmations(workflow_id)
        blockers: list[GuidedClosureBlockerV1] = []
        inputs: list[GuidedClosureInputV1] = []
        planned_node_ids = tuple(
            str(record.node_id) for record, _, _, _ in planned if record is not None
        )
        if self._has_active_work(workflow_id, planned_node_ids):
            blockers.append(
                GuidedClosureBlockerV1(
                    kind="nonterminal_work",
                    media_role="video",
                    status="working",
                    error_code="guided_closure_work_active",
                    allowed_actions=("wait",),
                )
            )

        for record, media_role, order, sequence_id in planned:
            if record is None:
                blockers.append(
                    GuidedClosureBlockerV1(
                        kind="missing",
                        sequence_id=sequence_id or None,
                        media_role=media_role,
                        status="missing",
                        error_code="guided_closure_media_missing",
                        allowed_actions=("retry", "replace", "exclude"),
                    )
                )
                continue
            node = nodes.get(record.node_id)
            if node is None:
                blockers.append(
                    _blocker(
                        "missing",
                        media_role,
                        record.node_id,
                        sequence_id,
                        "missing",
                        "guided_closure_media_missing",
                    )
                )
                continue
            if node.status != "ready" or node.output_asset_id is None:
                kind = "failed" if node.status == "failed" else "not_ready"
                blockers.append(
                    _blocker(
                        kind,
                        media_role,
                        node.node_id,
                        sequence_id,
                        node.status,
                        (
                            "guided_closure_media_failed"
                            if kind == "failed"
                            else "guided_closure_media_not_ready"
                        ),
                    )
                )
                continue
            try:
                asset = self._assets(node.output_asset_id)
            except (KeyError, LookupError, V2PersistenceError):
                blockers.append(
                    _blocker(
                        "unreadable",
                        media_role,
                        node.node_id,
                        sequence_id,
                        node.status,
                        "guided_closure_media_unreadable",
                    )
                )
                continue
            if (
                asset.status != "ready"
                or asset.media_type != media_role
                or asset.version_id is None
                or not self._asset_readable(asset)
            ):
                blockers.append(
                    _blocker(
                        "unreadable",
                        media_role,
                        node.node_id,
                        sequence_id,
                        node.status,
                        "guided_closure_media_unreadable",
                    )
                )
                continue
            confirmation = _current_confirmation(
                confirmations,
                document=document,
                node=node,
                asset=asset,
                media_role=media_role,
                sequence_id=sequence_id or None,
            )
            if confirmation is None:
                blockers.append(
                    _blocker(
                        "unconfirmed",
                        media_role,
                        node.node_id,
                        sequence_id,
                        node.status,
                        "guided_media_confirmation_missing",
                    )
                )
                continue
            inputs.append(
                GuidedClosureInputV1(
                    sequence_id=sequence_id or None,
                    order=order,
                    media_role=media_role,
                    node_id=node.node_id,
                    node_revision=node.revision,
                    asset_id=asset.asset_id,
                    asset_version_id=asset.version_id,
                    asset_digest=asset.checksum,
                    confirmation_id=confirmation.confirmation_id,
                )
            )

        if blockers:
            self._record_blocked(workflow_id, document, blockers)
            raise V2PersistenceError(
                "guided_closure_blocked",
                "Guided production closure is blocked by current media authority.",
                stage="guided_production_closure",
                details={
                    "plan_document_id": document.document_id,
                    "plan_revision": document.revision,
                    "blockers": [item.model_dump(mode="json") for item in blockers],
                },
            )

        confirmation_digest = _digest([item.confirmation_id for item in inputs])
        logical_identity = f"{document.document_id}:{document.revision}:{confirmation_digest}"
        return GuidedClosurePlanV1(
            closure_plan_id="closure_" + sha256(logical_identity.encode()).hexdigest()[:32],
            logical_identity=logical_identity,
            workflow_id=workflow_id,
            guidance_session_id=document.guidance_session_id,
            plan_document_id=document.document_id,
            plan_revision=document.revision,
            confirmation_digest=confirmation_digest,
            ordered_inputs=tuple(inputs),
            no_active_work=True,
            created_at=self._clock(),
        )

    def _record_blocked(self, workflow_id: str, document, blockers) -> None:
        digest = _digest([item.model_dump(mode="json") for item in blockers])
        self._events.append(
            V2EventInsert(
                workflow_id=workflow_id,
                event_type="guided_closure_blocked",
                transition_key=(
                    f"guided-closure:{document.document_id}:{document.revision}:{digest}:blocked"
                ),
                created_at=self._clock().isoformat(),
                payload={
                    "plan_document_id": document.document_id,
                    "plan_revision": document.revision,
                    "blockers": [item.model_dump(mode="json") for item in blockers],
                },
            )
        )


def _current_confirmation(
    confirmations: tuple[GuidedMediaConfirmationV1, ...],
    *,
    document,
    node: CanvasNodeV2,
    asset: ProjectAssetSummaryV2,
    media_role: str,
    sequence_id: str | None,
) -> GuidedMediaConfirmationV1 | None:
    return next(
        (
            item
            for item in confirmations
            if item.plan_document_id == document.document_id
            and item.plan_revision <= document.revision
            and item.node_id == node.node_id
            and item.node_revision == node.revision
            and item.asset_id == asset.asset_id
            and item.asset_version_id == asset.version_id
            and item.asset_digest == asset.checksum
            and item.media_role == media_role
            and item.sequence_id == sequence_id
        ),
        None,
    )


def _blocker(kind, media_role, node_id, sequence_id, status, error_code):
    return GuidedClosureBlockerV1(
        kind=kind,
        sequence_id=sequence_id or None,
        media_role=media_role,
        node_id=node_id,
        status=status,
        error_code=error_code,
        allowed_actions=("accept", "retry", "replace", "exclude"),
    )


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return sha256(encoded).hexdigest()


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guided_production_closure")
