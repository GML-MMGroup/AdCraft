from __future__ import annotations

from typing import Any

from app.schemas.workflow_v2 import V2AgentRoute, WorkflowItemV2, WorkflowSlotV2, WorkflowV2
from app.schemas.workflow_v2_specialist_ownership import (
    V2SpecialistOwnedPlan,
    V2SpecialistSlotPlan,
    V2SlotPromptContext,
)
from app.services.v2_main_to_multiview_consistency import is_main_to_multiview_slot


class V2SlotContextAssembler:
    def assemble(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        route: V2AgentRoute,
        owned_plan: V2SpecialistOwnedPlan,
        slot_plan: V2SpecialistSlotPlan,
        runtime_context: dict[str, Any] | None = None,
    ) -> V2SlotPromptContext:
        runtime_context = runtime_context or {}
        reference_asset_ids = _reference_asset_ids(slot, slot_plan, runtime_context)
        reference_version_ids = _reference_version_ids(slot, runtime_context)
        return V2SlotPromptContext(
            workflow_id=workflow.workflow_id,
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            slot_type=slot.slot_type,
            specialist=route.specialist,
            campaign_summary=_campaign_summary(workflow, runtime_context),
            item_summary=_item_summary(item),
            own_summary_prompt=slot_plan.summary_prompt,
            own_specialist_prompt=slot_plan.specialist_prompt,
            own_provider_prompt=slot_plan.provider_prompt,
            own_detail_prompts=_own_detail_prompts(item, slot, slot_plan),
            negative_prompt=slot_plan.negative_prompt,
            negative_constraints=slot_plan.negative_constraints,
            reference_asset_ids=reference_asset_ids,
            reference_version_ids=reference_version_ids,
            dependency_asset_summaries=_dependency_summaries(runtime_context),
            lightweight_owner_labels={
                "specialist": owned_plan.specialist,
                "node_id": slot.node_id,
                "item_id": item.item_id,
                "slot_id": slot.slot_id,
                "display_name": item.display_name,
            },
        )


def _campaign_summary(
    workflow: WorkflowV2,
    runtime_context: dict[str, Any],
) -> dict[str, Any]:
    handoff = runtime_context.get("specialist_handoff")
    if isinstance(handoff, dict):
        screenplay_slice = handoff.get("screenplay_slice")
        screenplay_slice = screenplay_slice if isinstance(screenplay_slice, dict) else {}
        hard_constraints = handoff.get("hard_constraints")
        hard_constraints = hard_constraints if isinstance(hard_constraints, dict) else {}
        return {
            "script_version_id": handoff.get("script_version_id"),
            "title": screenplay_slice.get("title"),
            "summary": screenplay_slice.get("summary"),
            "duration_seconds": hard_constraints.get("duration_seconds", workflow.duration_seconds),
            "aspect_ratio": hard_constraints.get("aspect_ratio", workflow.aspect_ratio),
            "audio_mode": hard_constraints.get("audio_mode", workflow.audio_mode),
        }
    selected_script_version_id = workflow.metadata.get("selected_script_version_id")
    if selected_script_version_id:
        return {
            "script_version_id": selected_script_version_id,
            "duration_seconds": workflow.duration_seconds,
            "aspect_ratio": workflow.aspect_ratio,
            "audio_mode": workflow.audio_mode,
        }
    return {
        "prompt": workflow.prompt,
        "duration_seconds": workflow.duration_seconds,
        "aspect_ratio": workflow.aspect_ratio,
        "audio_mode": workflow.audio_mode,
    }


def _item_summary(item: WorkflowItemV2) -> dict[str, Any]:
    summary = item.item_prompt or item.shot_summary_prompt or item.description
    return {
        "item_id": item.item_id,
        "item_type": item.item_type,
        "display_name": item.display_name,
        "summary_prompt": summary,
        "shot_id": item.shot_id,
        "shot_index": item.shot_index,
        "duration_seconds": item.duration_seconds,
    }


def _own_detail_prompts(
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    slot_plan: V2SpecialistSlotPlan,
) -> dict[str, Any]:
    if item.item_type != "shot":
        return dict(slot_plan.detail_prompts)
    item_details = dict(item.detail_prompts)
    if slot.slot_type.startswith("shot_cell_"):
        details = {
            key: value
            for key, value in slot_plan.detail_prompts.items()
            if key
            in {
                "prompt_contract",
                "prompt_contract_name",
                "prompt_contract_version",
                "selected_skill_ids",
                "selected_skill_paths",
                "skill_context_warnings",
                "quality_notes",
                "materializer_version",
            }
        }
        cell_prompts = item_details.get("cell_prompts")
        if isinstance(cell_prompts, dict):
            current_cell = cell_prompts.get(slot.slot_type)
            if isinstance(current_cell, dict):
                details["current_cell_prompt"] = dict(current_cell)
        for key in ("storyboard_content", "shot_style", "camera_language"):
            value = item_details.get(key)
            if value is not None:
                details[key] = value
        return details
    if slot.slot_type == "shot_video_segment":
        details = dict(slot_plan.detail_prompts)
        for key, value in item_details.items():
            if key != "cell_prompts":
                details[key] = value
        return details
    return dict(slot_plan.detail_prompts)


def _reference_asset_ids(
    slot: WorkflowSlotV2,
    slot_plan: V2SpecialistSlotPlan,
    runtime_context: dict[str, Any],
) -> list[str]:
    ids: list[str] = []
    if slot.slot_type == "shot_video_segment":
        ids.extend(str(asset_id) for asset_id in runtime_context.get("shot_cell_asset_ids", []))
    elif slot.slot_type == "final_video":
        ids.extend(
            str(asset_id) for asset_id in runtime_context.get("shot_video_segment_asset_ids", [])
        )
        bgm_asset_id = runtime_context.get("bgm_asset_id")
        if bgm_asset_id:
            ids.append(str(bgm_asset_id))
    elif slot.slot_type in {
        "product_multi_view_grid",
        "character_three_view",
        "scene_multi_view_grid",
    }:
        ids.extend(str(asset_id) for asset_id in runtime_context.get("dependency_asset_ids", []))
        ids.extend(slot_plan.reference_asset_ids)
        return list(dict.fromkeys(asset_id for asset_id in ids if asset_id))
    elif slot.slot_type.startswith("shot_cell_"):
        ids.extend(
            str(asset_id) for asset_id in runtime_context.get("visual_reference_asset_ids", [])
        )
    else:
        ids.extend(
            str(asset_id) for asset_id in runtime_context.get("item_reference_asset_ids", [])
        )
        ids.extend(str(asset_id) for asset_id in slot.implicit_reference_ids)
    if not is_main_to_multiview_slot(slot.slot_type):
        ids.extend(slot_plan.reference_asset_ids)
    ids.extend(slot.explicit_reference_ids)
    return list(dict.fromkeys(asset_id for asset_id in ids if asset_id))


def _reference_version_ids(
    slot: WorkflowSlotV2,
    runtime_context: dict[str, Any],
) -> list[str]:
    ids: list[str] = []
    if slot.current_working_version_id:
        ids.append(slot.current_working_version_id)
    ids.extend(str(version_id) for version_id in runtime_context.get("reference_version_ids", []))
    return list(dict.fromkeys(version_id for version_id in ids if version_id))


def _dependency_summaries(runtime_context: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = runtime_context.get("dependency_asset_summaries")
    if isinstance(summaries, list):
        return [dict(summary) for summary in summaries if isinstance(summary, dict)]
    return [
        {"asset_id": str(asset_id)}
        for asset_id in runtime_context.get("dependency_asset_ids", [])
        if str(asset_id)
    ]
