"""Read-only composition of immutable V2 authoring and typed operational state."""

from __future__ import annotations

from collections.abc import Mapping

from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.workflow_authoring_repository import WorkflowAuthoringRepository
from app.schemas.workflow_v2 import (
    WorkflowEdgeV2,
    WorkflowItemV2,
    WorkflowNodeV2,
    WorkflowRuntimeV2,
    WorkflowSlotV2,
    WorkflowV2,
)
from app.schemas.workflow_v2_authoring import (
    WorkflowAuthoringDocumentV2,
    WorkflowOperationalOverlayV2,
    WorkflowOperationalSlotErrorV2,
    WorkflowOperationalSlotOverlayV2,
)
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_workflow_store import V2WorkflowStore


class WorkflowV2ReadModelAssembler:
    """Compose the current Workflow without repairing or persisting projections."""

    def __init__(
        self,
        authoring_repository: WorkflowAuthoringRepository,
        projection_store: V2WorkflowStore,
        asset_store: V2AssetStoreService | None = None,
        asset_library_repository: V2AssetLibraryRepository | None = None,
    ) -> None:
        self._authoring_repository = authoring_repository
        self._projection_store = projection_store
        self._asset_store = asset_store
        self._asset_library_repository = asset_library_repository

    def assemble(self, workflow_id: str) -> WorkflowV2:
        """Return SQLite authoring with only allowlisted projection runtime applied."""

        current = self._authoring_repository.load_current(workflow_id)
        workflow = workflow_from_authoring(current.revision.document)
        source = self._projection_store.load_optional_projection_source(workflow_id)
        if source is not None:
            workflow = apply_operational_overlay(
                workflow, operational_overlay_from_workflow(source)
            )
        self._hydrate_slot_history_from_relations(workflow)
        self._hydrate_slot_reference_bindings(workflow)
        return workflow.model_copy(
            update={
                "project_id": current.project_id,
                "state_version": current.state_version,
                "semantic_revision_no": current.semantic_revision_no,
                "created_at": current.created_at,
                "updated_at": current.updated_at,
            }
        )

    def _hydrate_slot_history_from_relations(self, workflow: WorkflowV2) -> None:
        """Rebuild non-authoring history views from canonical asset relations."""

        if self._asset_store is None:
            return
        for node in workflow.nodes:
            for item in node.items:
                for slot in item.slots:
                    relations = self._asset_store.list_relations(
                        target_workflow_id=workflow.workflow_id,
                        target_slot_id=slot.slot_id,
                        relation_type="history_version_for_slot",
                    )
                    slot.history_version_ids = list(
                        dict.fromkeys(
                            str(relation.metadata["version_id"])
                            for relation in relations
                            if isinstance(relation.metadata.get("version_id"), str)
                            and relation.metadata["version_id"]
                        )
                    )

    def _hydrate_slot_reference_bindings(self, workflow: WorkflowV2) -> None:
        """Expose active version-pinned SQLite references on their owning slots."""

        if self._asset_library_repository is None:
            return
        for node in workflow.nodes:
            for item in node.items:
                for slot in item.slots:
                    bindings = self._asset_library_repository.list_bindings(
                        workflow_id=workflow.workflow_id,
                        target_slot_id=slot.slot_id,
                        binding_type="reference_for_slot",
                    )
                    if not bindings:
                        continue
                    versions = self._asset_library_repository.resolve_versions(
                        tuple(binding.version_id for binding in bindings)
                    )
                    versions_by_id = {version.version_id: version for version in versions}
                    slot.explicit_reference_ids = list(
                        dict.fromkeys(
                            [
                                *slot.explicit_reference_ids,
                                *(binding.asset_id for binding in bindings),
                            ]
                        )
                    )
                    slot.metadata["reference_bindings"] = [
                        {
                            "binding_id": binding.binding_id,
                            "relation_id": binding.binding_id,
                            "selection_group_id": binding.selection_group_id,
                            "source_entity_id": binding.source_entity_id,
                            "asset_id": binding.asset_id,
                            "version_id": binding.version_id,
                            "reference_role": binding.reference_role,
                            "use_as_prompt": binding.use_as_prompt,
                            "sort_order": binding.sort_order,
                            "public_url": f"/media/{versions_by_id[binding.version_id].storage_key}",
                            "metadata_path": None,
                        }
                        for binding in bindings
                    ]


def workflow_from_authoring(document: WorkflowAuthoringDocumentV2) -> WorkflowV2:
    """Construct a runtime-shaped Workflow using authoring fields only."""

    timeline_by_item_id = {timeline.item_id: timeline for timeline in document.timelines}
    nodes: list[WorkflowNodeV2] = []
    for node in document.nodes:
        items: list[WorkflowItemV2] = []
        for item in node.items:
            timeline = timeline_by_item_id.get(item.item_id)
            items.append(
                WorkflowItemV2(
                    item_id=item.item_id,
                    node_id=item.node_id,
                    item_type=item.item_type,
                    display_name=item.display_name,
                    description=item.description,
                    item_prompt=item.item_prompt,
                    system_suggested_prompt=item.system_suggested_prompt,
                    user_prompt=item.user_prompt,
                    prompt_source=item.prompt_source,
                    manual_prompt_dirty=item.manual_prompt_dirty,
                    lifecycle_state=item.lifecycle_state,
                    shot_id=item.shot_id,
                    shot_index=item.shot_index,
                    aspect_ratio=item.aspect_ratio,
                    duration_seconds=item.duration_seconds,
                    summary_prompt=item.summary_prompt,
                    cell_prompts=[dict(value) for value in item.cell_prompts],
                    shot_summary_prompt=item.shot_summary_prompt,
                    detail_prompts=dict(item.detail_prompts),
                    reference_item_ids=list(item.reference_item_ids),
                    primary_scene_item_id=item.primary_scene_item_id,
                    reference_source=item.reference_source,
                    timeline_plan={} if timeline is None else dict(timeline.timeline_plan),
                    timeline_clips=[]
                    if timeline is None
                    else [dict(clip) for clip in timeline.timeline_clips],
                    slots=[
                        WorkflowSlotV2(
                            slot_id=slot.slot_id,
                            node_id=slot.node_id,
                            item_id=slot.item_id,
                            slot_type=slot.slot_type,
                            media_type=slot.media_type,
                            required=slot.required,
                            slot_prompt=slot.slot_prompt,
                            system_suggested_prompt=slot.system_suggested_prompt,
                            user_prompt=slot.user_prompt,
                            negative_prompt=slot.negative_prompt,
                            dialogue_prompt=slot.dialogue_prompt,
                            audio_description_prompt=slot.audio_description_prompt,
                            voice_style_prompt=slot.voice_style_prompt,
                            negative_constraints=slot.negative_constraints,
                            prompt_source=slot.prompt_source,
                            manual_prompt_dirty=slot.manual_prompt_dirty,
                            media_prompt_asset_ids=list(slot.media_prompt_asset_ids),
                            implicit_reference_ids=list(slot.implicit_reference_ids),
                            explicit_reference_ids=list(slot.explicit_reference_ids),
                            dependency_slot_ids=list(slot.dependency_slot_ids),
                            provider=slot.provider,
                            provider_params=dict(slot.provider_params),
                            selected_asset_id=slot.selected_asset_id,
                            selected_version_id=slot.selected_version_id,
                            metadata=dict(slot.authoring_metadata),
                        )
                        for slot in item.slots
                    ],
                    metadata=dict(item.authoring_metadata),
                )
            )
        nodes.append(
            WorkflowNodeV2(
                node_id=node.node_id,
                node_type=node.node_type,
                title=node.title,
                status="not_ready",
                position=dict(node.position),
                items=items,
                metadata=dict(node.authoring_metadata),
            )
        )
    return WorkflowV2(
        workflow_id=document.workflow_id,
        name=document.name,
        description=document.description,
        prompt=document.prompt,
        duration_seconds=document.duration_seconds,
        aspect_ratio=document.aspect_ratio,
        output_resolution=document.output_resolution,
        audio_mode=document.audio_mode,
        nodes=nodes,
        edges=[
            WorkflowEdgeV2(
                edge_id=edge.edge_id,
                source_node_id=edge.source_node_id,
                target_node_id=edge.target_node_id,
                edge_kind=edge.edge_kind,
                label=edge.label,
                metadata=dict(edge.metadata),
            )
            for edge in document.edges
        ],
        metadata=_workflow_metadata_from_context(document),
        created_at="",
        updated_at="",
    )


def operational_overlay_from_workflow(workflow: WorkflowV2) -> WorkflowOperationalOverlayV2:
    """Extract only explicit runtime fields from an existing JSON projection."""

    slots: list[WorkflowOperationalSlotOverlayV2] = []
    for node in workflow.nodes:
        for item in node.items:
            for slot in item.slots:
                candidate = {
                    "slot_id": slot.slot_id,
                    "status": slot.status,
                    "current_working_asset_id": slot.current_working_asset_id,
                    "current_working_version_id": slot.current_working_version_id,
                    **_allowed_slot_metadata(slot.metadata),
                }
                try:
                    slots.append(WorkflowOperationalSlotOverlayV2.model_validate(candidate))
                except ValueError:
                    continue
    cooldowns = _provider_cooldowns(workflow.metadata)
    runtime = None
    if workflow.runtime is not None:
        runtime = {
            "workflow_id": workflow.runtime.workflow_id,
            "running_node_ids": tuple(workflow.runtime.running_node_ids),
            "running_item_ids": tuple(workflow.runtime.running_item_ids),
            "running_slot_ids": tuple(workflow.runtime.running_slot_ids),
            "waiting_slot_ids": tuple(workflow.runtime.waiting_slot_ids),
            "failed_slot_ids": tuple(workflow.runtime.failed_slot_ids),
        }
    return WorkflowOperationalOverlayV2.model_validate(
        {
            "workflow_id": workflow.workflow_id,
            "runtime": runtime,
            "provider_cooldowns": cooldowns,
            "nodes": [{"node_id": node.node_id, "status": node.status} for node in workflow.nodes],
            "items": [
                {"item_id": item.item_id, "status": item.status}
                for node in workflow.nodes
                for item in node.items
            ],
            "slots": slots,
        }
    )


def apply_operational_overlay(
    workflow: WorkflowV2,
    overlay: WorkflowOperationalOverlayV2,
) -> WorkflowV2:
    """Apply only validated runtime fields to an authoring-derived Workflow."""

    if overlay.workflow_id != workflow.workflow_id:
        return workflow
    node_statuses = {entry.node_id: entry.status for entry in overlay.nodes}
    item_statuses = {entry.item_id: entry.status for entry in overlay.items}
    slots = {entry.slot_id: entry for entry in overlay.slots}
    for node in workflow.nodes:
        if node.node_id in node_statuses:
            node.status = node_statuses[node.node_id]
        for item in node.items:
            if item.item_id in item_statuses:
                item.status = item_statuses[item.item_id]
            for slot in item.slots:
                entry = slots.get(slot.slot_id)
                if entry is None:
                    continue
                slot.status = entry.status
                slot.current_working_asset_id = entry.current_working_asset_id
                slot.current_working_version_id = entry.current_working_version_id
                slot.metadata = {
                    **slot.metadata,
                    **_slot_metadata_from_overlay(entry),
                }
    if overlay.runtime is not None:
        workflow.runtime = WorkflowRuntimeV2(
            workflow_id=overlay.runtime.workflow_id,
            running_node_ids=list(overlay.runtime.running_node_ids),
            running_item_ids=list(overlay.runtime.running_item_ids),
            running_slot_ids=list(overlay.runtime.running_slot_ids),
            waiting_slot_ids=list(overlay.runtime.waiting_slot_ids),
            failed_slot_ids=list(overlay.runtime.failed_slot_ids),
        )
    if overlay.provider_cooldowns:
        workflow.metadata["provider_cooldowns"] = {
            media_type: cooldown.model_dump(mode="json")
            for media_type, cooldown in overlay.provider_cooldowns.items()
        }
    return workflow


def _workflow_metadata_from_context(document: WorkflowAuthoringDocumentV2) -> dict[str, object]:
    context = document.creative_context
    metadata = {
        key: value
        for key, value in {
            "request": dict(context.request),
            "script_plan": dict(context.screenplay),
            "visual_style_contract": dict(context.visual_style),
            "creative_inventory": dict(context.creative_inventory),
            "specialist_briefs": dict(context.specialist_briefs),
            "storyboard_config": dict(context.storyboard_config),
            "planning_constraints": dict(context.planning_constraints),
        }.items()
        if value
    }
    metadata.update(dict(context.planning))
    for key, value in {
        "script_reconciliation": dict(context.script_reconciliation),
        "visual_style_scope_audit": dict(context.visual_style_scope_audit),
        "expert_brief_plan": dict(context.expert_brief_plan),
        "specialist_quality_audit": dict(context.specialist_quality_audit),
    }.items():
        if value:
            metadata[key] = value
    if context.planner_warnings:
        metadata["planner_warnings"] = list(context.planner_warnings)
    if context.input_asset_descriptors:
        metadata["input_asset_descriptors"] = [
            dict(value) for value in context.input_asset_descriptors
        ]
    return metadata


def _allowed_slot_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    allowed_keys = (
        "provider_task_id",
        "remote_task_id",
        "provider_result_id",
        "waiting_reason",
        "blocked_reason",
        "skipped_reason",
        "generation_error",
        "generation_error_code",
        "recoverable",
        "interrupted_at",
        "interrupted_execution_id",
        "last_runtime_event_seq",
        "last_runtime_event_type",
        "provider_retry_attempts",
        "provider_retry_policy",
        "provider_recovery_used",
        "last_provider_error_code",
        "last_provider_error_message",
        "final_provider_error_code",
        "final_provider_error_message",
        "stale",
    )
    values = {key: metadata[key] for key in allowed_keys if key in metadata}
    error = metadata.get("error")
    if isinstance(error, Mapping):
        try:
            values["error"] = WorkflowOperationalSlotErrorV2.model_validate(error)
        except ValueError:
            pass
    return values


def _provider_cooldowns(metadata: Mapping[str, object]) -> dict[str, object]:
    raw = metadata.get("provider_cooldowns")
    if not isinstance(raw, Mapping):
        return {}
    values: dict[str, object] = {}
    for media_type in ("image", "video"):
        value = raw.get(media_type)
        if isinstance(value, Mapping):
            values[media_type] = dict(value)
    return values


def _slot_metadata_from_overlay(entry: WorkflowOperationalSlotOverlayV2) -> dict[str, object]:
    payload = entry.model_dump(
        mode="python",
        exclude={"slot_id", "status", "current_working_asset_id", "current_working_version_id"},
        exclude_none=True,
    )
    return payload
