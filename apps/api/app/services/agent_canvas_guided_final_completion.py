"""Post-Export completion authority for guided production."""

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
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_working_document_repository import AgentWorkingDocumentRepository
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.schemas.agent_canvas import CanvasNodeV2, ProjectAssetSummaryV2
from app.schemas.agent_canvas_creative_session import GuidedSessionStateV2
from app.schemas.agent_canvas_editing import EditingNodeContentV2
from app.schemas.agent_canvas_production_closure import (
    GuidedEditingPreparationReceiptV1,
    GuidedEditingTopologyReceiptV2,
    GuidedEditingMediaClosureReceiptV2,
    GuidedClosurePlanV1,
    GuidedFinalCompletionReceiptV1,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_guided_production_closure import GuidedProductionClosureService
from app.services.agent_working_documents import AgentWorkingDocumentService


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
        documents: AgentWorkingDocumentService | None = None,
        closure: GuidedProductionClosureService | None = None,
        verify_complete_export: Callable[[GuidedClosurePlanV1, str, str], None] | None = None,
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
        self._documents = documents
        self._closure = closure
        self._verify_complete_export = verify_complete_export

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
        if isinstance(
            preparation, (GuidedEditingTopologyReceiptV2, GuidedEditingMediaClosureReceiptV2)
        ):
            return self._complete_current_media(preparation, export_id)
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

    def _complete_current_media(
        self,
        preparation: GuidedEditingTopologyReceiptV2 | GuidedEditingMediaClosureReceiptV2,
        export_id: str,
    ) -> GuidedFinalCompletionReceiptV1:
        if self._closure is None or self._documents is None or self._verify_complete_export is None:
            raise _error(
                "guided_closure_blocked",
                "Editing topology is not full current-media confirmation evidence.",
            )
        session = self._require_current_preparation(preparation)
        existing = self._receipts.find_completion_for_export(export_id)
        if existing is not None:
            if (
                session.status == "completed"
                and session.completion.final_completion_receipt_id == existing.receipt_id
            ):
                return existing
            raise _error(
                "guided_export_preparation_stale",
                "Completed delivery is not the current Guidance authority.",
            )
        if session.status != "active" or (
            session.awaiting is not None
            and session.awaiting.kind not in {"manual_node_run", "media_review"}
        ):
            raise _error(
                "guided_closure_blocked",
                "Guidance is paused or has an unresolved authoring choice.",
            )
        if not isinstance(self._workflows, AgentCanvasWorkflowRepository):
            raise _error(
                "guided_closure_blocked",
                "Full media proof requires canonical workflow persistence.",
            )
        workflow_id, node_id = preparation.workflow_id, preparation.editing_node_id
        workflow = self._workflows.get_workflow(workflow_id)
        document = self._documents.get_document(workflow_id, preparation.plan_document_id)
        closure = self._closure.freeze(
            workflow_id, document.document_id, expected_plan_revision=document.revision
        )
        self._verify_complete_export(closure, node_id, export_id)
        runtime = self._exports.get(export_id)
        frozen_manifest = self._exports.manifest(export_id)
        commit = self._commits.receipt_for_export(export_id)
        node = self._workflows.get_node(workflow_id, node_id)
        content = EditingNodeContentV2.model_validate(node.structured_content)
        if (
            runtime.status != "completed"
            or runtime.output_asset_id is None
            or commit.outcome != "completed"
            or commit.asset_id != runtime.output_asset_id
            or commit.version_id is None
            or not node.metadata.get("guided_production")
            or node.output_asset_id != runtime.output_asset_id
            or content.manifest.manifest_revision != runtime.manifest_revision
            or frozen_manifest.manifest_revision != runtime.manifest_revision
        ):
            raise _error(
                "guided_export_commit_mismatch",
                "Terminal Export evidence does not match current guided delivery.",
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
        now = self._clock()
        manifest_digest = sha256(
            json.dumps(
                frozen_manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        identity = f"media_closure:{closure.closure_plan_id}:{node_id}:{manifest_digest}"
        proof = GuidedEditingMediaClosureReceiptV2(
            receipt_id="preparation_" + sha256(identity.encode()).hexdigest()[:32],
            logical_identity=identity,
            workflow_id=workflow_id,
            plan_document_id=document.document_id,
            plan_revision=document.revision,
            editing_node_id=node_id,
            editing_node_revision=node.revision,
            binding_ids=tuple(
                binding.binding_id
                for binding in workflow.bindings
                if binding.target_node_id == node_id
            ),
            manifest_revision=content.manifest.manifest_revision,
            manifest_digest=manifest_digest,
            closure_plan_id=closure.closure_plan_id,
            confirmation_digest=closure.confirmation_digest,
            committed_at=now,
        )
        logical_identity = (
            f"{proof.receipt_id}:{export_id}:{asset.asset_id}:{asset.version_id}:{asset.checksum}"
        )
        receipt = GuidedFinalCompletionReceiptV1(
            receipt_id="completion_" + sha256(logical_identity.encode()).hexdigest()[:32],
            logical_identity=logical_identity,
            workflow_id=workflow_id,
            preparation_receipt_id=proof.receipt_id,
            export_id=export_id,
            export_generation=self._exports.lease_generation(export_id),
            final_asset_id=asset.asset_id,
            final_asset_version_id=asset.version_id,
            final_asset_digest=asset.checksum,
            completion_revision=session.revision + 1,
            completed_at=now,
        )
        return self._commit_current_media(
            proof=proof,
            receipt=receipt,
            closure=closure,
            session=session,
            workflow_revision=workflow.revision,
            node=node,
            asset=asset,
        )

    def _commit_current_media(
        self,
        *,
        proof: GuidedEditingMediaClosureReceiptV2,
        receipt: GuidedFinalCompletionReceiptV1,
        closure: GuidedClosurePlanV1,
        session: GuidedSessionStateV2,
        workflow_revision: int,
        node: CanvasNodeV2,
        asset: ProjectAssetSummaryV2,
    ) -> GuidedFinalCompletionReceiptV1:
        """Fence source snapshots and append all full-delivery projections atomically."""

        workflow_id, node_id, export_id = (
            proof.workflow_id,
            proof.editing_node_id,
            receipt.export_id,
        )
        now = receipt.completed_at
        completion = session.completion.model_copy(
            update={
                "authoring": "ready",
                "delivery": "ready",
                "plan_document_id": proof.plan_document_id,
                "plan_revision": proof.plan_revision,
                "editing_preparation": "prepared",
                "editing_node_id": node_id,
                "preparation_receipt_id": proof.receipt_id,
                "manifest_revision": proof.manifest_revision,
                "export_status": "completed",
                "export_id": export_id,
                "final_completion_receipt_id": receipt.receipt_id,
                "final_asset_id": asset.asset_id,
                "matching_asset_ids": tuple(
                    dict.fromkeys((*session.completion.matching_asset_ids, asset.asset_id))
                ),
            }
        )
        journey = session.journey.model_copy(
            update={
                "stage": "completed",
                "stage_status": "completed",
                "stage_revision": session.journey.stage_revision + 1,
                "active_action": None,
                "suspended_action": None,
            }
        )
        database = self._workflows.database
        with database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                self._workflows.require_workflow_revision_in_transaction(
                    connection, workflow_id, workflow_revision
                )
                AgentWorkingDocumentRepository.require_revision_in_transaction(
                    connection,
                    workflow_id=workflow_id,
                    document_id=proof.plan_document_id,
                    expected_revision=proof.plan_revision,
                )
                self._closure.require_no_active_work(
                    workflow_id, tuple(item.node_id for item in closure.ordered_inputs)
                )
                self._workflows.require_node_revision_in_transaction(
                    connection,
                    workflow_id=workflow_id,
                    node_id=node_id,
                    expected_revision=node.revision,
                    expected_output_asset_id=asset.asset_id,
                    expected_status="ready",
                )
                asset_repository = V2AssetLibraryRepository(database)
                for source in closure.ordered_inputs:
                    self._workflows.require_node_revision_in_transaction(
                        connection,
                        workflow_id=workflow_id,
                        node_id=source.node_id,
                        expected_revision=source.node_revision,
                        expected_output_asset_id=source.asset_id,
                        expected_status="ready",
                    )
                    version = asset_repository.find_version(
                        asset_id=source.asset_id, connection=connection
                    )
                    if (
                        version is None
                        or version.version_id != source.asset_version_id
                        or version.sha256 != source.asset_digest
                        or version.status != "ready"
                    ):
                        raise _error(
                            "guided_media_confirmation_stale",
                            "Confirmed source version changed before delivery.",
                        )
                final_version = asset_repository.find_version(
                    asset_id=asset.asset_id, connection=connection
                )
                if (
                    final_version is None
                    or final_version.version_id != asset.version_id
                    or final_version.sha256 != asset.checksum
                    or final_version.status != "ready"
                ):
                    raise _error(
                        "guided_final_asset_unreadable", "Final Asset changed before delivery."
                    )
                self._receipts.save_preparation_in_transaction(connection, proof)
                self._receipts.save_completion_in_transaction(connection, receipt)
                self._conversations.complete_guidance_session_in_transaction(
                    connection,
                    session.session_id,
                    expected_session_revision=session.revision,
                    completion=completion,
                    journey=journey,
                    now=now.isoformat(),
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        execution_id=export_id,
                        node_id=node_id,
                        event_type="guided_production_completed",
                        transition_key=f"guided-completion:{receipt.receipt_id}",
                        created_at=now.isoformat(),
                        payload={
                            "final_completion_receipt_id": receipt.receipt_id,
                            "preparation_receipt_id": proof.receipt_id,
                            "export_id": export_id,
                            "final_asset_id": asset.asset_id,
                            "session_revision": session.revision + 1,
                            "refresh": ["conversation", "workflow", "assets", "runtime"],
                        },
                    ),
                )
                connection.commit()
            except V2PersistenceError:
                connection.rollback()
                persisted = self._receipts.find_completion_for_export(export_id)
                if persisted is not None and persisted.logical_identity == receipt.logical_identity:
                    current = self._conversations.get_guidance_session(workflow_id)
                    if (
                        current.status == "completed"
                        and current.completion.final_completion_receipt_id == persisted.receipt_id
                    ):
                        return persisted
                raise
            except BaseException:
                connection.rollback()
                raise
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
            journey=session.journey.model_copy(
                update={
                    "stage": "completed",
                    "stage_status": "completed",
                    "stage_revision": session.journey.stage_revision + 1,
                    "active_action": None,
                    "suspended_action": None,
                }
            ),
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
        preparation: GuidedEditingPreparationReceiptV1 | GuidedEditingTopologyReceiptV2,
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
