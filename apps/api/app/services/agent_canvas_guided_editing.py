"""Prepare one guided Editing node from currently available planned media."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import cast

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
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
from app.schemas.agent_working_documents import (
    AttachEditingNodePatchV2,
    StoryboardProductionPlanContentV2,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_working_documents import AgentWorkingDocumentService


class GuidedEditingPreparationService:
    """Materialize available plan outputs without starting an Export."""

    def __init__(
        self,
        *,
        workflows: AgentCanvasWorkflowRepository,
        documents: AgentWorkingDocumentService,
        conversations: AgentCanvasConversationRepository,
        events: EventRepository,
        asset_resolver,
    ) -> None:
        self._workflows = workflows
        self._documents = documents
        self._conversations = conversations
        self._events = events
        self._asset_resolver = asset_resolver

    def prepare(
        self,
        workflow_id: str,
        plan_document_id: str,
        *,
        expected_plan_revision: int,
    ) -> EditingPreparationResultV2:
        agent_run_id = "guided_editing_preparation"
        plan_document = self._documents.get_document(workflow_id, plan_document_id)
        if (
            plan_document.kind != "storyboard_production_plan"
            or plan_document.revision != expected_plan_revision
        ):
            raise V2PersistenceError(
                "editing_preparation_plan_conflict",
                "Editing preparation requires the current Storyboard plan revision.",
                stage="guided_editing_preparation",
            )
        plan = cast(StoryboardProductionPlanContentV2, plan_document.content)
        workflow = self._workflows.get_workflow(workflow_id)
        nodes = {node.node_id: node for node in workflow.nodes}
        video_records = {
            record.sequence_id: record
            for record in plan.node_records
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
                for record in plan.node_records
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

        existing_record = next(
            (record for record in plan.node_records if record.node_role == "editing"),
            None,
        )
        editing_node_id = (
            existing_record.node_id
            if existing_record is not None
            else _stable_id("node_guided_editing", plan_document.guidance_session_id)
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
        changed = False
        now = datetime.now(timezone.utc)
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

        session = self._conversations.get_guidance_session(workflow_id)
        if (
            session.completion.editing_preparation != "prepared"
            or session.completion.editing_node_id != editing_node_id
        ):
            self._conversations.complete_guidance_session(
                session.session_id,
                expected_session_revision=session.revision,
                completion=session.completion.model_copy(
                    update={
                        "editing_preparation": "prepared",
                        "editing_node_id": editing_node_id,
                    }
                ),
            )
            changed = True

        final_content = EditingNodeContentV2.model_validate(
            self._workflows.get_node(workflow_id, editing_node_id).structured_content
        )
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
                    created_at=datetime.now(timezone.utc).isoformat(),
                    payload={
                        "editing_node_id": editing_node_id,
                        "bound_video_node_ids": list(result.bound_video_node_ids),
                        "bound_audio_node_ids": list(result.bound_audio_node_ids),
                        "omitted_node_ids": list(result.omitted_node_ids),
                        "manifest_revision": result.manifest_revision,
                        "plan_document_id": plan_document.document_id,
                        "plan_revision": plan_document.revision,
                        "guidance_session_id": plan_document.guidance_session_id,
                        "agent_run_id": agent_run_id,
                    },
                )
            )
        return result

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


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode()).hexdigest()[:24]
    return f"{prefix}_{digest}"
