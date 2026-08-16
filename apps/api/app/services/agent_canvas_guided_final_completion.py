"""Post-Export completion authority for guided production."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
from typing import Protocol

from app.persistence.agent_canvas_production_closure_repository import (
    AgentCanvasProductionClosureRepository,
)
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.schemas.agent_canvas import CanvasNodeV2, ProjectAssetSummaryV2
from app.schemas.agent_canvas_creative_session import GuidedSessionStateV2
from app.schemas.agent_canvas_editing import EditingNodeContentV2
from app.schemas.agent_canvas_production_closure import (
    GuidedEditingPreparationReceiptV1,
    GuidedFinalCompletionReceiptV1,
)
from app.schemas.v2_persistence import V2EventInsert


Clock = Callable[[], datetime]


class _WorkflowReader(Protocol):
    def get_node(self, workflow_id: str, node_id: str) -> CanvasNodeV2: ...


class GuidedFinalCompletionService:
    """Publish final guided completion from exact terminal Export evidence."""

    def __init__(
        self,
        *,
        workflows: _WorkflowReader,
        exports,
        commits,
        assets: Callable[[str], ProjectAssetSummaryV2],
        asset_readable: Callable[[ProjectAssetSummaryV2], bool],
        receipts: AgentCanvasProductionClosureRepository,
        conversations,
        events: EventRepository,
        clock: Clock = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._workflows = workflows
        self._exports = exports
        self._commits = commits
        self._assets = assets
        self._asset_readable = asset_readable
        self._receipts = receipts
        self._conversations = conversations
        self._events = events
        self._clock = clock

    def complete(
        self,
        workflow_id: str,
        editing_node_id: str,
        export_id: str,
    ) -> GuidedFinalCompletionReceiptV1 | None:
        preparation = self._receipts.find_preparation_for_editing(
            workflow_id,
            editing_node_id,
        )
        if preparation is None:
            return None
        self._require_current_preparation(preparation)
        existing = self._receipts.find_completion_for_export(export_id)
        if existing is not None:
            self._complete_session(existing, preparation)
            return existing

        runtime = self._exports.get(export_id)
        if runtime.status != "completed" or runtime.output_asset_id is None:
            if runtime.error is not None:
                raise V2PersistenceError(
                    runtime.error.code,
                    runtime.error.message,
                    stage="guided_final_completion",
                    details={"retryable": runtime.error.retryable, "export_id": export_id},
                )
            raise _error(
                "guided_export_not_completed",
                "Guided production remains Editing-ready until Export completes.",
            )
        commit = self._commits.receipt_for_export(export_id)
        if (
            commit.outcome != "completed"
            or commit.asset_id != runtime.output_asset_id
            or commit.version_id is None
        ):
            raise _error(
                "guided_export_commit_mismatch",
                "Terminal Export evidence does not match its committed final Asset.",
            )
        node = self._workflows.get_node(workflow_id, editing_node_id)
        content = EditingNodeContentV2.model_validate(node.structured_content)
        if (
            not node.metadata.get("guided_production")
            or runtime.manifest_revision != preparation.manifest_revision
            or content.manifest.manifest_revision != preparation.manifest_revision
        ):
            raise _error(
                "guided_export_preparation_stale",
                "Editing Export does not match current guided preparation authority.",
            )
        try:
            asset = self._assets(runtime.output_asset_id)
        except (KeyError, LookupError, V2PersistenceError) as error:
            raise _error(
                "guided_final_asset_unreadable",
                "Final Editing Asset is not readable through canonical storage.",
            ) from error
        if (
            asset.status != "ready"
            or asset.media_type != "video"
            or asset.version_id != commit.version_id
            or not self._asset_readable(asset)
        ):
            raise _error(
                "guided_final_asset_unreadable",
                "Final Editing Asset is not readable through canonical storage.",
            )

        session = self._conversations.get_guidance_session(workflow_id)
        logical_identity = (
            f"{preparation.receipt_id}:{export_id}:{asset.asset_id}:"
            f"{asset.version_id}:{asset.checksum}"
        )
        receipt = self._receipts.save_completion(
            GuidedFinalCompletionReceiptV1(
                receipt_id="completion_" + sha256(logical_identity.encode()).hexdigest()[:32],
                logical_identity=logical_identity,
                workflow_id=workflow_id,
                preparation_receipt_id=preparation.receipt_id,
                export_id=export_id,
                export_generation=self._exports.lease_generation(export_id),
                final_asset_id=asset.asset_id,
                final_asset_version_id=asset.version_id or "",
                final_asset_digest=asset.checksum,
                completion_revision=session.revision + 1,
                completed_at=self._clock(),
            )
        )
        self._complete_session(receipt, preparation)
        return receipt

    def _complete_session(self, receipt, preparation) -> None:
        session = self._require_current_preparation(preparation)
        if (
            session.status == "completed"
            and session.completion.final_completion_receipt_id == receipt.receipt_id
        ):
            return
        completion = session.completion.model_copy(
            update={
                "authoring": "ready",
                "delivery": "ready",
                "plan_document_id": preparation.plan_document_id,
                "plan_revision": preparation.plan_revision,
                "editing_preparation": "prepared",
                "editing_node_id": preparation.editing_node_id,
                "preparation_receipt_id": preparation.receipt_id,
                "manifest_revision": preparation.manifest_revision,
                "export_status": "completed",
                "export_id": receipt.export_id,
                "final_completion_receipt_id": receipt.receipt_id,
                "final_asset_id": receipt.final_asset_id,
                "matching_asset_ids": tuple(
                    dict.fromkeys((*session.completion.matching_asset_ids, receipt.final_asset_id))
                ),
            }
        )
        updated = self._conversations.complete_guidance_session(
            session.session_id,
            expected_session_revision=session.revision,
            completion=completion,
        )
        self._events.append(
            V2EventInsert(
                workflow_id=receipt.workflow_id,
                execution_id=receipt.export_id,
                node_id=preparation.editing_node_id,
                event_type="guided_production_completed",
                transition_key=f"guided-completion:{receipt.receipt_id}",
                created_at=receipt.completed_at.isoformat(),
                payload={
                    "final_completion_receipt_id": receipt.receipt_id,
                    "preparation_receipt_id": preparation.receipt_id,
                    "export_id": receipt.export_id,
                    "final_asset_id": receipt.final_asset_id,
                    "session_revision": updated.revision,
                    "refresh": ["conversation", "workflow", "assets", "runtime"],
                },
            )
        )

    def _require_current_preparation(
        self,
        preparation: GuidedEditingPreparationReceiptV1,
    ) -> GuidedSessionStateV2:
        session = self._conversations.get_guidance_session(preparation.workflow_id)
        completion = session.completion
        if (
            completion.preparation_receipt_id != preparation.receipt_id
            or completion.editing_node_id != preparation.editing_node_id
            or completion.manifest_revision != preparation.manifest_revision
        ):
            raise _error(
                "guided_export_preparation_stale",
                "Editing Export does not match current guided preparation authority.",
            )
        return session


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guided_final_completion")
