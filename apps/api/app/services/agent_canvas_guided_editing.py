"""Prepare one guided Editing node from currently available planned media."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_production_closure_repository import (
    AgentCanvasProductionClosureRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.event_repository import EventRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    CanvasNodeV2,
    CanvasPositionV2,
    ProjectAssetSummaryV2,
)
from app.schemas.agent_canvas_editing import (
    EditingBgmEntryV2,
    EditingManifestV2,
    EditingNodeContentV2,
    EditingPreparationResultV2,
    EditingVideoEntryV2,
)
from app.schemas.agent_canvas_production_closure import (
    GuidedEditingPreparationReceiptV1,
)
from app.schemas.agent_working_documents import (
    AttachEditingNodePatchV2,
    StoryboardPlannedNodeV3,
    StoryboardProductionPlanContentV2,
    StoryboardProductionPlanContentV3,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_working_documents import AgentWorkingDocumentService
from app.services.agent_canvas_guided_production_closure import (
    GuidedProductionClosureService,
)
from app.services.agent_canvas_guided_duration import GuidedDurationAuthorityPolicy
from app.services.agent_canvas_editing_timeline import normalize_manifest


class GuidedEditingPreparationService:
    """Materialize available plan outputs without starting an Export."""

    def __init__(
        self,
        *,
        workflows: AgentCanvasWorkflowRepository,
        documents: AgentWorkingDocumentService,
        conversations: AgentCanvasConversationRepository,
        events: EventRepository,
        asset_resolver=None,
        closure: GuidedProductionClosureService | None = None,
        receipts: AgentCanvasProductionClosureRepository | None = None,
        requirements: AgentCanvasRequirementRepository | None = None,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._workflows = workflows
        self._documents = documents
        self._conversations = conversations
        self._events = events
        self._asset_resolver = asset_resolver
        self._closure = closure
        self._receipts = receipts
        self._clock = clock
        self._requirements = requirements or AgentCanvasRequirementRepository(workflows.database)
        self._duration_authority = GuidedDurationAuthorityPolicy()

    def prepare(
        self,
        workflow_id: str,
        plan_document_id: str,
        *,
        expected_plan_revision: int,
    ) -> EditingPreparationResultV2:
        agent_run_id = "guided_editing_preparation"
        existing_preparation = (
            self._receipts.find_preparation(
                workflow_id,
                plan_document_id,
                expected_plan_revision,
            )
            if self._closure is not None and self._receipts is not None
            else None
        )
        plan_document = self._documents.get_document(workflow_id, plan_document_id)
        if plan_document.kind != "storyboard_production_plan" or (
            existing_preparation is None and plan_document.revision != expected_plan_revision
        ):
            raise V2PersistenceError(
                "editing_preparation_plan_conflict",
                "Editing preparation requires the current Storyboard plan revision.",
                stage="guided_editing_preparation",
            )
        plan = plan_document.content
        if not isinstance(
            plan,
            (StoryboardProductionPlanContentV2, StoryboardProductionPlanContentV3),
        ):
            raise V2PersistenceError(
                "editing_preparation_plan_invalid",
                "Editing preparation requires a Storyboard production plan.",
                stage="guided_editing_preparation",
            )
        self._duration_authority.validate_plan(
            self._requirements.get_current(workflow_id),
            plan,
        )
        if existing_preparation is not None:
            return self._preparation_result(existing_preparation, replayed=True)
        closure_plan = (
            self._closure.freeze(
                workflow_id,
                plan_document_id,
                expected_plan_revision=expected_plan_revision,
            )
            if self._closure is not None
            else None
        )
        plan_records = _plan_node_records(plan)
        workflow = self._workflows.get_workflow(workflow_id)
        nodes = {node.node_id: node for node in workflow.nodes}
        if closure_plan is not None:
            available_videos = tuple(
                nodes[item.node_id]
                for item in closure_plan.ordered_inputs
                if item.media_role == "video"
            )
            audio_inputs = tuple(
                nodes[item.node_id]
                for item in closure_plan.ordered_inputs
                if item.media_role == "audio"
            )
            available_audio = audio_inputs[0] if audio_inputs else None
            omitted_node_ids: tuple[str, ...] = ()
        else:
            video_records = {
                record.sequence_id: record
                for record in plan_records
                if record.node_role == "video_segment" and record.sequence_id is not None
            }
            ordered_video_nodes = tuple(
                nodes[record.node_id]
                for segment in plan.segments
                if (record := video_records.get(segment.sequence_id)) is not None
                and record.node_id in nodes
            )
            audio_node = next(
                (
                    nodes[record.node_id]
                    for record in plan_records
                    if record.node_role == "bgm" and record.node_id in nodes
                ),
                None,
            )
            available_videos = tuple(
                node for node in ordered_video_nodes if self._ready_media(node, "video")
            )
            available_audio = (
                audio_node
                if audio_node is not None and self._ready_media(audio_node, "audio")
                else None
            )
            omitted_node_ids = tuple(
                node.node_id for node in ordered_video_nodes if node not in available_videos
            )
            if audio_node is not None and available_audio is None:
                omitted_node_ids += (audio_node.node_id,)
            if omitted_node_ids:
                blocker_reasons = [
                    (
                        "planned_audio_not_ready"
                        if node_id == getattr(audio_node, "node_id", None)
                        else "planned_video_not_ready"
                    )
                    for node_id in omitted_node_ids
                ]
                raise V2PersistenceError(
                    "guided_closure_blocked",
                    "Guided Editing requires every planned media input to be ready.",
                    stage="guided_editing_preparation",
                    details={
                        "blocker_node_ids": list(omitted_node_ids),
                        "blocker_reasons": blocker_reasons,
                    },
                )

        prior_editing_record = next(
            (record for record in plan_records if record.node_role == "editing"),
            None,
        )
        editing_node_id = _stable_id(
            "node_guided_editing",
            (
                closure_plan.closure_plan_id
                if closure_plan is not None
                else plan_document.guidance_session_id
            ),
        )
        existing_record = (
            prior_editing_record
            if prior_editing_record is not None and prior_editing_record.node_id == editing_node_id
            else None
        )
        current_bindings = {
            _binding_source_id(binding): binding
            for binding in workflow.bindings
            if binding.target_node_id == editing_node_id
        }
        desired_sources = (*available_videos, *((available_audio,) if available_audio else ()))
        desired_bindings = tuple(
            (
                current_bindings[source.node_id].model_copy(
                    update={"order": index, "updated_at": datetime.now(timezone.utc)}
                )
                if source.node_id in current_bindings
                else _editing_binding(
                    workflow_id,
                    editing_node_id,
                    source,
                    order=index,
                )
            )
            for index, source in enumerate(desired_sources)
        )
        manifest = EditingManifestV2(
            video_entries=tuple(
                EditingVideoEntryV2(binding_id=binding.binding_id)
                for binding in desired_bindings[: len(available_videos)]
            ),
            bgm=(
                EditingBgmEntryV2(binding_id=desired_bindings[-1].binding_id)
                if available_audio is not None
                else None
            ),
        )
        current_manifest = None
        if editing_node_id in nodes:
            current_manifest = EditingNodeContentV2.model_validate(
                nodes[editing_node_id].structured_content
            ).manifest
        if self._asset_resolver is not None:
            source_durations = {
                ("binding", binding.binding_id): asset.duration_seconds
                for binding, source in zip(
                    desired_bindings[: len(available_videos)],
                    available_videos,
                    strict=True,
                )
                if (asset := self._asset_resolver(source.output_asset_id)).duration_seconds
                is not None
            }
            if len(source_durations) == len(available_videos):
                manifest = normalize_manifest(
                    manifest,
                    current_manifest=current_manifest,
                    source_durations=source_durations,
                )
        changed = False
        now = self._clock()
        if editing_node_id not in nodes:
            editing_node = CanvasNodeV2(
                node_id=editing_node_id,
                workflow_id=workflow_id,
                node_type="editing",
                creative_role="editing",
                title="Guided Editing",
                status="draft",
                structured_content=EditingNodeContentV2(manifest=manifest).model_dump(mode="json"),
                metadata={
                    "guided_production": True,
                    "guidance_session_id": plan_document.guidance_session_id,
                    "source_agent_document_id": plan_document.document_id,
                    "source_agent_document_revision": plan_document.revision,
                    "source_agent_document_digest": plan_document.content_digest,
                },
                position=CanvasPositionV2(x=960, y=640),
                revision=1,
                created_at=now,
                updated_at=now,
            )
            changed = True
        else:
            editing_node = nodes[editing_node_id]
            current_content = EditingNodeContentV2.model_validate(editing_node.structured_content)
            comparable = manifest.model_copy(
                update={"manifest_revision": current_content.manifest.manifest_revision}
            )
            if comparable != current_content.manifest:
                manifest = manifest.model_copy(
                    update={"manifest_revision": (current_content.manifest.manifest_revision + 1)}
                )
                editing_node = editing_node.model_copy(
                    update={
                        "structured_content": current_content.model_copy(
                            update={"manifest": manifest, "dirty": True}
                        ).model_dump(mode="json"),
                        "revision": editing_node.revision + 1,
                        "updated_at": now,
                    }
                )
                changed = True
            current_source_order = tuple(
                _binding_source_id(binding)
                for binding in sorted(
                    current_bindings.values(),
                    key=lambda item: (item.order, item.binding_id),
                )
            )
            if current_source_order != tuple(source.node_id for source in desired_sources) or any(
                current_bindings[source.node_id].order != index
                for index, source in enumerate(desired_sources)
                if source.node_id in current_bindings
            ):
                changed = True

        if changed:
            self._workflows.upsert_guided_editing(
                editing_node,
                desired_bindings,
                expected_revision=workflow.revision,
            )

        if existing_record is None:
            if isinstance(plan, StoryboardProductionPlanContentV3):
                next_content = plan.model_copy(
                    update={
                        "planned_nodes": tuple(
                            record for record in plan.planned_nodes if record.node_role != "editing"
                        )
                        + (
                            StoryboardPlannedNodeV3(
                                node_role="editing",
                                node_id=editing_node_id,
                                node_revision=editing_node.revision,
                                materialization_id=(
                                    f"guided-editing:{closure_plan.closure_plan_id}"
                                    if closure_plan is not None
                                    else f"guided-editing:{editing_node_id}"
                                ),
                            ),
                        )
                    }
                )
                updated_plan = self._documents.commit_content_mutation(
                    workflow_id=workflow_id,
                    agent_run_id=agent_run_id,
                    document_id=plan_document.document_id,
                    expected_revision=plan_document.revision,
                    operation="attach_guided_editing_node",
                    idempotency_key=f"attach-editing:{editing_node_id}",
                    next_content=next_content,
                )
            else:
                updated_plan = self._documents.apply_agent_patch(
                    workflow_id,
                    agent_run_id,
                    AttachEditingNodePatchV2(
                        operation="attach_editing_node",
                        document_id=plan_document.document_id,
                        expected_revision=plan_document.revision,
                        idempotency_key=f"attach-editing:{editing_node_id}",
                        node_id=editing_node_id,
                    ),
                ).document
            plan_document = updated_plan
            changed = True

        final_node = self._workflows.get_node(workflow_id, editing_node_id)
        final_content = EditingNodeContentV2.model_validate(final_node.structured_content)
        preparation_receipt = None
        if closure_plan is not None:
            if self._receipts is None:
                raise V2PersistenceError(
                    "guided_preparation_receipt_unavailable",
                    "Guided Editing preparation receipt authority is unavailable.",
                    stage="guided_editing_preparation",
                )
            manifest_payload = json.dumps(
                final_content.manifest.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            )
            manifest_digest = hashlib.sha256(manifest_payload.encode()).hexdigest()
            logical_identity = f"{closure_plan.closure_plan_id}:{editing_node_id}:{manifest_digest}"
            preparation_receipt = self._receipts.save_preparation(
                GuidedEditingPreparationReceiptV1(
                    receipt_id=(
                        "preparation_" + hashlib.sha256(logical_identity.encode()).hexdigest()[:32]
                    ),
                    logical_identity=logical_identity,
                    workflow_id=workflow_id,
                    closure_plan_id=closure_plan.closure_plan_id,
                    plan_document_id=closure_plan.plan_document_id,
                    plan_revision=closure_plan.plan_revision,
                    confirmation_digest=closure_plan.confirmation_digest,
                    editing_node_id=editing_node_id,
                    editing_node_revision=final_node.revision,
                    binding_ids=tuple(binding.binding_id for binding in desired_bindings),
                    manifest_revision=final_content.manifest.manifest_revision,
                    manifest_digest=manifest_digest,
                    committed_at=now,
                )
            )

        session = self._conversations.get_guidance_session(workflow_id)
        if (
            session.completion.editing_preparation != "prepared"
            or session.completion.editing_node_id != editing_node_id
            or (
                preparation_receipt is not None
                and session.completion.preparation_receipt_id != preparation_receipt.receipt_id
            )
        ):
            update_completion = getattr(
                self._conversations,
                "update_guidance_completion",
                None,
            )
            if update_completion is None:
                update_completion = self._conversations.complete_guidance_session
            update_completion(
                session.session_id,
                expected_session_revision=session.revision,
                completion=session.completion.model_copy(
                    update={
                        "authoring": "ready",
                        "delivery": "ready",
                        "plan_document_id": plan_document.document_id,
                        "plan_revision": plan_document.revision,
                        "editing_preparation": "prepared",
                        "editing_node_id": editing_node_id,
                        "preparation_receipt_id": (
                            preparation_receipt.receipt_id
                            if preparation_receipt is not None
                            else None
                        ),
                        "manifest_revision": final_content.manifest.manifest_revision,
                    }
                ),
            )
            changed = True

        result = EditingPreparationResultV2(
            workflow_id=workflow_id,
            plan_document_id=plan_document.document_id,
            editing_node_id=editing_node_id,
            bound_video_node_ids=tuple(node.node_id for node in available_videos),
            bound_audio_node_ids=(
                (available_audio.node_id,) if available_audio is not None else ()
            ),
            omitted_node_ids=omitted_node_ids,
            manifest_revision=final_content.manifest.manifest_revision,
            replayed=not changed,
        )
        if changed:
            identity = ":".join(
                (
                    plan_document.document_id,
                    *result.bound_video_node_ids,
                    *result.bound_audio_node_ids,
                    *result.omitted_node_ids,
                )
            )
            self._events.append(
                V2EventInsert(
                    workflow_id=workflow_id,
                    node_id=editing_node_id,
                    event_type="editing_prepared",
                    transition_key=f"editing_prepared:{hashlib.sha256(identity.encode()).hexdigest()}",
                    created_at=now.isoformat(),
                    payload={
                        "editing_node_id": editing_node_id,
                        "bound_video_node_ids": list(result.bound_video_node_ids),
                        "bound_audio_node_ids": list(result.bound_audio_node_ids),
                        "omitted_node_ids": list(result.omitted_node_ids),
                        "manifest_revision": result.manifest_revision,
                        "closure_plan_id": (
                            closure_plan.closure_plan_id if closure_plan is not None else None
                        ),
                        "preparation_receipt_id": (
                            preparation_receipt.receipt_id
                            if preparation_receipt is not None
                            else None
                        ),
                        "plan_document_id": plan_document.document_id,
                        "plan_revision": plan_document.revision,
                        "guidance_session_id": plan_document.guidance_session_id,
                        "agent_run_id": agent_run_id,
                    },
                )
            )
            self._events.append(
                V2EventInsert(
                    workflow_id=workflow_id,
                    node_id=editing_node_id,
                    event_type="guided_editing_ready",
                    transition_key=(
                        "guided-editing-ready:"
                        f"{preparation_receipt.receipt_id if preparation_receipt else identity}"
                    ),
                    created_at=now.isoformat(),
                    payload={
                        "editing_node_id": editing_node_id,
                        "manifest_revision": result.manifest_revision,
                        "plan_document_id": plan_document.document_id,
                        "plan_revision": plan_document.revision,
                        "closure_plan_id": (
                            closure_plan.closure_plan_id if closure_plan is not None else None
                        ),
                        "preparation_receipt_id": (
                            preparation_receipt.receipt_id
                            if preparation_receipt is not None
                            else None
                        ),
                    },
                )
            )
        return result

    def _preparation_result(
        self,
        receipt: GuidedEditingPreparationReceiptV1,
        *,
        replayed: bool,
    ) -> EditingPreparationResultV2:
        workflow = self._workflows.get_workflow(receipt.workflow_id)
        binding_ids = set(receipt.binding_ids)
        ordered_bindings = tuple(
            sorted(
                (binding for binding in workflow.bindings if binding.binding_id in binding_ids),
                key=lambda item: (item.order, item.binding_id),
            )
        )
        nodes = {node.node_id: node for node in workflow.nodes}
        ordered_nodes = tuple(
            nodes[node_id]
            for binding in ordered_bindings
            if (node_id := _binding_source_id(binding)) in nodes
        )
        return EditingPreparationResultV2(
            workflow_id=receipt.workflow_id,
            plan_document_id=receipt.plan_document_id,
            editing_node_id=receipt.editing_node_id,
            bound_video_node_ids=tuple(
                node.node_id for node in ordered_nodes if node.node_type == "video"
            ),
            bound_audio_node_ids=tuple(
                node.node_id for node in ordered_nodes if node.node_type == "audio"
            ),
            omitted_node_ids=(),
            manifest_revision=receipt.manifest_revision,
            replayed=replayed,
        )

    def _ready_media(self, node: CanvasNodeV2, media_type: str) -> bool:
        if node.status != "ready" or node.output_asset_id is None:
            return False
        try:
            asset: ProjectAssetSummaryV2 = self._asset_resolver(node.output_asset_id)
        except (KeyError, LookupError, V2PersistenceError):
            return False
        return asset.status == "ready" and asset.media_type == media_type


def _editing_binding(
    workflow_id: str,
    editing_node_id: str,
    source: CanvasNodeV2,
    *,
    order: int,
) -> CanvasBindingV2:
    now = datetime.now(timezone.utc)
    input_role = "audio_reference" if source.node_type == "audio" else "video_reference"
    semantic_role = "bgm_reference" if source.node_type == "audio" else "video_segment"
    return CanvasBindingV2(
        binding_id=_stable_id("binding_guided_editing", editing_node_id, source.node_id),
        workflow_id=workflow_id,
        source=CanvasBindingSourceNodeV2(source_node_id=source.node_id),
        target_node_id=editing_node_id,
        input_role=input_role,
        required=False,
        enabled=True,
        order=order,
        metadata={
            "guided_editing_preparation": True,
            "semantic_reference_role": semantic_role,
        },
        created_at=now,
        updated_at=now,
    )


def _binding_source_id(binding: CanvasBindingV2) -> str:
    if isinstance(binding.source, CanvasBindingSourceNodeV2):
        return binding.source.node_id
    return ""


def _plan_node_records(
    plan: StoryboardProductionPlanContentV2 | StoryboardProductionPlanContentV3,
):
    if isinstance(plan, StoryboardProductionPlanContentV3):
        return plan.planned_nodes
    return plan.node_records


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode()).hexdigest()[:24]
    return f"{prefix}_{digest}"
