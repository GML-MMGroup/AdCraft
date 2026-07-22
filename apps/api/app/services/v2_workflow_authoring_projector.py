"""Side-effect-free projection from runtime WorkflowV2 to authoring state."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import cast

from pydantic import JsonValue

from app.schemas.workflow_v2 import WorkflowItemV2, WorkflowSlotV2, WorkflowV2
from app.schemas.workflow_v2_authoring import (
    WorkflowAuthoringCreativeContextV2,
    WorkflowAuthoringDocumentV2,
    WorkflowAuthoringEdgeV2,
    WorkflowAuthoringItemV2,
    WorkflowAuthoringNodeV2,
    WorkflowAuthoringReferenceV2,
    WorkflowAuthoringSlotV2,
    WorkflowAuthoringTimelineV2,
)


class WorkflowAuthoringProjector:
    """Build a compact, explicit semantic document without I/O."""

    _CREATIVE_CONTEXT_KEYS = {
        "request": "request",
        "script_plan": "screenplay",
        "visual_style_contract": "visual_style",
        "creative_inventory": "creative_inventory",
        "specialist_briefs": "specialist_briefs",
        "storyboard_config": "storyboard_config",
        "planning_constraints": "planning_constraints",
    }
    _ITEM_METADATA_KEYS = (
        "script_text",
        "script_brief_id",
        "script_version_id",
        "script_plan_version",
        "materializer_mode",
        "model_id",
        "selected_skill_ids",
        "skill_context_warnings",
        "quality_notes",
        "materializer_version",
        "source_script_shot",
        "desired_duration_seconds",
        "time_segments",
        "detail_prompt_dirty_fields",
        "detail_prompts_outdated",
        "source_script_brief_id",
        "source_script_version_id",
        "source_scene_ids",
        "source_shot_ids",
        "brief_kind",
        "item_source",
        "creative_brief",
        "asset_prompts",
        "specialist_quality_audit",
        "source_skill_ids",
        "brief_builder_version",
        "creative_inventory_id",
        "creative_inventory_hash",
        "creative_inventory_version",
        "source_inventory_item_id",
        "identity_spec_version",
        "identity_spec_hash",
        "identity_spec",
        "product_identity_constraints",
        "available_composition_asset_ids",
        "explicit_reference_asset_ids",
        "reference_relation_ids",
        "reference_mode",
    )
    _NODE_METADATA_KEYS = (
        "resolved_media_type",
        "resolved_node_role",
    )
    _SLOT_METADATA_KEYS = (
        "source_script_brief_id",
        "source_script_version_id",
        "source_brief_item_id",
        "specialist_type",
        "slot_type",
        "asset_prompt_hash",
        "specialist_quality_audit",
        "source_skill_ids",
        "brief_builder_version",
        "creative_inventory_id",
        "creative_inventory_hash",
        "creative_inventory_version",
        "source_inventory_item_id",
        "source_identity_spec_version",
        "source_identity_spec_hash",
        "identity_spec_source",
        "reference_item_ids",
        "system_detail_context_outdated",
        "visual_style_contract",
        "screenplay_slice",
    )
    _PLANNING_METADATA_KEYS = (
        "original_user_prompt",
        "creative_inventory_spec",
        "creative_inventory_id",
        "creative_inventory_hash",
        "creative_inventory_version",
        "intent_contract_version",
        "intent_plan",
        "intent_validation",
        "intent_repair_used",
        "intent_fallback_used",
        "explicit_constraints",
        "inventory_reconciliation_audit",
        "planning_degraded",
        "fallback_stage",
        "original_error_code",
        "v2_planner_version",
        "script_writer_version",
        "expert_brief_builder_version",
        "created_by_backend_revision",
        "generation_integrity_version",
        "selected_script_version_id",
        "shot_reference_plan",
    )
    _NAMED_CONTEXT_KEYS = {
        "script_reconciliation": "script_reconciliation",
        "visual_style_scope_audit": "visual_style_scope_audit",
        "expert_brief_plan": "expert_brief_plan",
        "specialist_quality_audit": "specialist_quality_audit",
    }

    def project(self, workflow: WorkflowV2) -> WorkflowAuthoringDocumentV2:
        """Return the allowlisted authoring representation for ``workflow``."""

        references: list[WorkflowAuthoringReferenceV2] = []
        timelines: list[WorkflowAuthoringTimelineV2] = []
        nodes: list[WorkflowAuthoringNodeV2] = []
        for node in workflow.nodes:
            items: list[WorkflowAuthoringItemV2] = []
            for item in node.items:
                slots = tuple(self._project_slot(slot) for slot in item.slots)
                items.append(self._project_item(item, slots))
                if item.timeline_plan or item.timeline_clips:
                    timelines.append(
                        WorkflowAuthoringTimelineV2(
                            item_id=item.item_id,
                            timeline_plan=_json_map(item.timeline_plan),
                            timeline_clips=tuple(_json_map(clip) for clip in item.timeline_clips),
                        )
                    )
                for slot in item.slots:
                    if (
                        slot.media_prompt_asset_ids
                        or slot.implicit_reference_ids
                        or slot.explicit_reference_ids
                    ):
                        references.append(
                            WorkflowAuthoringReferenceV2(
                                node_id=slot.node_id,
                                item_id=slot.item_id,
                                slot_id=slot.slot_id,
                                reference_asset_ids=tuple(slot.media_prompt_asset_ids),
                                implicit_reference_ids=tuple(slot.implicit_reference_ids),
                                explicit_reference_ids=tuple(slot.explicit_reference_ids),
                            )
                        )
            nodes.append(
                WorkflowAuthoringNodeV2(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    title=node.title,
                    position=dict(node.position),
                    authoring_metadata={
                        key: _json_value(node.metadata[key])
                        for key in self._NODE_METADATA_KEYS
                        if key in node.metadata
                    },
                    items=tuple(items),
                )
            )

        return WorkflowAuthoringDocumentV2(
            workflow_id=workflow.workflow_id,
            name=workflow.name,
            description=workflow.description,
            prompt=workflow.prompt,
            duration_seconds=workflow.duration_seconds,
            aspect_ratio=workflow.aspect_ratio,
            output_resolution=workflow.output_resolution,
            audio_mode=workflow.audio_mode,
            creative_context=self._project_creative_context(workflow.metadata),
            nodes=tuple(nodes),
            edges=tuple(
                WorkflowAuthoringEdgeV2(
                    edge_id=edge.edge_id,
                    source_node_id=edge.source_node_id,
                    target_node_id=edge.target_node_id,
                    edge_kind=edge.edge_kind,
                    label=edge.label,
                    metadata=_json_map(edge.metadata),
                )
                for edge in workflow.edges
            ),
            references=tuple(references),
            timelines=tuple(timelines),
        )

    @staticmethod
    def canonical_bytes(document: WorkflowAuthoringDocumentV2) -> bytes:
        """Serialize a validated document with canonical compact JSON ordering."""

        return json.dumps(
            document.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    @classmethod
    def content_hash(cls, document: WorkflowAuthoringDocumentV2) -> str:
        """Return the stable lowercase SHA-256 hash of canonical authoring state."""

        return hashlib.sha256(cls.canonical_bytes(document)).hexdigest()

    def _project_creative_context(
        self, metadata: Mapping[str, object]
    ) -> WorkflowAuthoringCreativeContextV2:
        values: dict[str, dict[str, JsonValue]] = {}
        for source_key, target_key in self._CREATIVE_CONTEXT_KEYS.items():
            source_value = metadata.get(source_key)
            if isinstance(source_value, Mapping):
                values[target_key] = (
                    _planning_context_without_local_skill_paths(source_value)
                    if source_key == "script_plan"
                    else _json_map(source_value)
                )
        for source_key, target_key in self._NAMED_CONTEXT_KEYS.items():
            source_value = metadata.get(source_key)
            if isinstance(source_value, Mapping):
                values[target_key] = _planning_context_without_local_skill_paths(source_value)
        planning = {
            key: _json_value(metadata[key])
            for key in self._PLANNING_METADATA_KEYS
            if key in metadata
        }
        if planning:
            values["planning"] = planning
        planner_warnings = metadata.get("planner_warnings")
        if isinstance(planner_warnings, list):
            values["planner_warnings"] = tuple(_json_value(value) for value in planner_warnings)
        input_asset_descriptors = metadata.get("input_asset_descriptors")
        if isinstance(input_asset_descriptors, list) and all(
            isinstance(value, Mapping) for value in input_asset_descriptors
        ):
            values["input_asset_descriptors"] = tuple(
                _json_map(value) for value in input_asset_descriptors
            )
        return WorkflowAuthoringCreativeContextV2(**values)

    def _project_item(
        self,
        item: WorkflowItemV2,
        slots: tuple[WorkflowAuthoringSlotV2, ...],
    ) -> WorkflowAuthoringItemV2:
        return WorkflowAuthoringItemV2(
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
            cell_prompts=tuple(_json_map(prompt) for prompt in item.cell_prompts),
            shot_summary_prompt=item.shot_summary_prompt,
            detail_prompts=_json_map(item.detail_prompts),
            reference_item_ids=tuple(item.reference_item_ids),
            primary_scene_item_id=item.primary_scene_item_id,
            reference_source=item.reference_source,
            authoring_metadata={
                key: _json_value(item.metadata[key])
                for key in self._ITEM_METADATA_KEYS
                if key in item.metadata
            },
            slots=slots,
        )

    def _project_slot(self, slot: WorkflowSlotV2) -> WorkflowAuthoringSlotV2:
        return WorkflowAuthoringSlotV2(
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
            media_prompt_asset_ids=tuple(slot.media_prompt_asset_ids),
            implicit_reference_ids=tuple(slot.implicit_reference_ids),
            explicit_reference_ids=tuple(slot.explicit_reference_ids),
            dependency_slot_ids=tuple(slot.dependency_slot_ids),
            provider=slot.provider,
            provider_params=_json_map(slot.provider_params),
            selected_asset_id=slot.selected_asset_id,
            selected_version_id=slot.selected_version_id,
            authoring_metadata={
                key: _json_value(slot.metadata[key])
                for key in self._SLOT_METADATA_KEYS
                if key in slot.metadata
            },
        )


def _json_map(value: Mapping[str, object]) -> dict[str, JsonValue]:
    return {str(key): _json_value(child) for key, child in value.items()}


def _planning_context_without_local_skill_paths(
    value: Mapping[str, object],
) -> dict[str, JsonValue]:
    """Project typed planning DTOs without deployment-local skill source paths."""

    return {
        str(key): _planning_context_value(child)
        for key, child in value.items()
        if key not in {"selected_skill_paths", "source_skill_paths"}
    }


def _planning_context_value(value: object) -> JsonValue:
    if isinstance(value, Mapping):
        return {
            str(key): _planning_context_value(child)
            for key, child in value.items()
            if key not in {"selected_skill_paths", "source_skill_paths"}
        }
    if isinstance(value, (list, tuple)):
        return [_planning_context_value(child) for child in value]
    return _json_value(value)


def _json_value(value: object) -> JsonValue:
    """Normalize known source metadata into JSON-only authoring content."""

    return cast(JsonValue, json.loads(json.dumps(value, ensure_ascii=False, default=str)))
