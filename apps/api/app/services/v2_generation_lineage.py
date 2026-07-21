from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from app.schemas.workflow_v2 import V2ReferenceBundle, WorkflowItemV2, WorkflowSlotV2, WorkflowV2
from app.schemas.workflow_v2_screenplay import V2GenerationLineage


def build_generation_lineage(
    workflow: WorkflowV2,
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    *,
    specialist_handoff: dict[str, Any] | None,
    reference_bundle: V2ReferenceBundle,
) -> V2GenerationLineage:
    handoff = specialist_handoff or {}
    screenplay_slice = handoff.get("screenplay_slice")
    screenplay_slice = screenplay_slice if isinstance(screenplay_slice, dict) else {}
    selected_references = handoff.get("selected_references")
    selected_references = selected_references if isinstance(selected_references, list) else []
    reference_version_ids = [
        str(reference.get("version_id"))
        for reference in selected_references
        if isinstance(reference, dict) and reference.get("version_id")
    ]
    if not reference_version_ids:
        reference_version_ids = [
            asset.version_id
            for asset in [
                *reference_bundle.explicit_reference_assets,
                *reference_bundle.implicit_reference_assets,
            ]
        ]
    script_version_id = str(
        handoff.get("script_version_id")
        or workflow.metadata.get("selected_script_version_id")
        or "script_version_unavailable"
    )
    source_scene_ids = _string_list(screenplay_slice.get("source_scene_ids"))
    source_shot_ids = _string_list(screenplay_slice.get("source_shot_ids"))
    if not source_scene_ids:
        source_scene_ids = _string_list(item.metadata.get("source_scene_ids"))
    if not source_shot_ids:
        source_shot_ids = _string_list(item.metadata.get("source_shot_ids"))
    if item.shot_id and item.shot_id not in source_shot_ids:
        source_shot_ids.append(item.shot_id)
    system_prompt = str(
        handoff.get("system_suggested_prompt")
        or slot.system_suggested_prompt
        or item.system_suggested_prompt
        or ""
    )
    user_prompt = str(
        handoff.get("latest_user_instruction")
        or handoff.get("user_prompt")
        or slot.user_prompt
        or item.user_prompt
        or ""
    )
    context = {
        "workflow_id": workflow.workflow_id,
        "node_id": slot.node_id,
        "item_id": item.item_id,
        "slot_id": slot.slot_id,
        "script_version_id": script_version_id,
        "source_scene_ids": source_scene_ids,
        "source_shot_ids": source_shot_ids,
        "system_suggested_prompt": system_prompt,
        "user_prompt": user_prompt,
        "hard_constraints": handoff.get("hard_constraints", {}),
        "screenplay_slice": screenplay_slice,
        "selected_reference_version_ids": _ordered_unique_strings(reference_version_ids),
    }
    return V2GenerationLineage(
        script_version_id=script_version_id,
        source_scene_ids=source_scene_ids,
        source_shot_ids=source_shot_ids,
        system_prompt_hash=_hash_text(system_prompt),
        user_prompt_hash=_hash_text(user_prompt),
        selected_reference_version_ids=_ordered_unique_strings(reference_version_ids),
        generation_context_hash=_hash_json(context),
    )


def _hash_text(value: str) -> str:
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


def _hash_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(encoded.encode("utf-8")).hexdigest()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item) for item in value if str(item)))


def _ordered_unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
