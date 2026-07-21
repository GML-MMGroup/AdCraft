from __future__ import annotations

import json
from typing import Any, cast

from app.schemas.workflow_v2 import (
    V2PromptMaterializerMode,
    V2SpecialistPromptRequest,
    V2SpecialistPromptResult,
)
from app.schemas.workflow_v2_prompt_contracts import (
    V2CharacterMainPromptPlan,
    V2CharacterThreeViewPromptPlan,
    V2ProductMainPromptPlan,
    V2ProductMultiViewPromptPlan,
    V2PromptContractModel,
    V2SceneMainPromptPlan,
    V2SceneMultiViewPromptPlan,
    V2ShotCellPromptPlan,
    V2ShotVideoPromptPlan,
    prompt_contract_model_for_slot,
    prompt_contract_name_for_slot,
    prompt_contract_version,
)

_COMMON_CONTRACT_FIELDS = {
    "summary_prompt",
    "specialist_prompt",
    "provider_prompt",
    "negative_prompt",
    "negative_constraints",
    "reference_asset_ids",
    "quality_notes",
    "warnings",
}


def is_prompt_contract_slot(slot_type: str) -> bool:
    try:
        prompt_contract_model_for_slot(slot_type)
    except ValueError:
        return False
    return True


def specialist_result_from_prompt_contract(
    contract: V2PromptContractModel,
    *,
    slot_type: str,
    materializer_mode: V2PromptMaterializerMode,
    model_id: str | None,
    selected_skill_ids: list[str] | None = None,
    selected_skill_paths: list[str] | None = None,
    skill_context_warnings: list[dict[str, Any]] | None = None,
    materializer_version: str | None = None,
    extra_detail_prompts: dict[str, Any] | None = None,
    extra_warnings: list[dict[str, Any]] | None = None,
    extra_quality_notes: list[str] | None = None,
) -> V2SpecialistPromptResult:
    contract_payload = contract.model_dump(mode="json")
    detail_prompts = {
        **_contract_detail_prompts(contract_payload),
        **dict(extra_detail_prompts or {}),
        "prompt_contract": contract_payload,
        "prompt_contract_name": prompt_contract_name_for_slot(slot_type),
        "prompt_contract_version": prompt_contract_version(),
    }
    warnings = _dedupe_warning_dicts(
        [
            *_warning_dicts(getattr(contract, "warnings", [])),
            *_warning_dicts(extra_warnings or []),
        ]
    )
    quality_notes = list(
        dict.fromkeys(
            [
                *getattr(contract, "quality_notes", []),
                *(extra_quality_notes or []),
                "slot_prompt_contract_validated",
            ]
        )
    )
    negative_constraints = getattr(contract, "negative_constraints", None)
    if isinstance(contract, V2ShotVideoPromptPlan):
        negative_constraints = contract.video_negative_constraints
    return V2SpecialistPromptResult(
        summary_prompt=contract.summary_prompt,
        specialist_prompt=getattr(contract, "specialist_prompt", None)
        or f"{prompt_contract_name_for_slot(slot_type)} structured prompt",
        detail_prompts=detail_prompts,
        provider_prompt=contract.provider_prompt,
        negative_prompt=getattr(contract, "negative_prompt", None),
        negative_constraints=negative_constraints,
        reference_asset_ids=list(contract.reference_asset_ids),
        warnings=warnings,
        materializer_mode=materializer_mode,
        model_id=model_id,
        selected_skill_ids=list(selected_skill_ids or []),
        selected_skill_paths=list(selected_skill_paths or []),
        skill_context_warnings=list(skill_context_warnings or []),
        quality_notes=quality_notes,
        materializer_version=materializer_version,
    )


def prompt_contract_from_specialist_result(
    request: V2SpecialistPromptRequest,
    result: V2SpecialistPromptResult,
    *,
    slot_type: str,
) -> V2PromptContractModel:
    existing = result.detail_prompts.get("prompt_contract")
    if isinstance(existing, dict):
        return cast(
            V2PromptContractModel,
            prompt_contract_model_for_slot(slot_type).model_validate(existing),
        )
    if slot_type == "product_main_image":
        return V2ProductMainPromptPlan(
            **_base_payload(request, result),
            layout_intent="single_product",
            forbidden_layouts=["multi_view", "grid", "contact_sheet", "collage"],
        )
    if slot_type == "product_multi_view_grid":
        return V2ProductMultiViewPromptPlan(
            **_base_payload(request, result),
            layout_intent="product_grid_2x2",
            grid_layout="2x2",
            view_count=4,
            same_product_required=True,
            must_use_reference_slot_type="product_main_image",
        )
    if slot_type == "character_main_image":
        return V2CharacterMainPromptPlan(
            **_base_payload(request, result),
            layout_intent="single_character",
            forbidden_layouts=[
                "three_view",
                "turnaround",
                "multi_view",
                "grid",
                "sheet",
                "contact_sheet",
                "collage",
            ],
        )
    if slot_type == "character_three_view":
        return V2CharacterThreeViewPromptPlan(
            **_base_payload(request, result),
            layout_intent="character_three_view",
            required_views=["front", "side", "back"],
            same_identity_required=True,
            must_use_reference_slot_type="character_main_image",
        )
    if slot_type == "scene_main_image":
        return V2SceneMainPromptPlan(
            **_base_payload(request, result),
            layout_intent="single_scene",
            forbidden_layouts=[
                "multi_view",
                "grid",
                "collage",
                "storyboard_sheet",
                "split_screen",
            ],
        )
    if slot_type == "scene_multi_view_grid":
        return V2SceneMultiViewPromptPlan(
            **_base_payload(request, result),
            layout_intent="scene_grid_2x2",
            grid_layout="2x2",
            view_count=4,
            same_location_required=True,
            must_use_reference_slot_type="scene_main_image",
        )
    if slot_type.startswith("shot_cell_"):
        cell_index = _shot_cell_index(slot_type)
        return V2ShotCellPromptPlan(
            **_base_payload(request, result),
            layout_intent="single_keyframe",
            cell_role=_shot_cell_role(cell_index),
            shot_id=str(request.target.get("item_id") or request.target.get("shot_id") or "shot"),
            cell_index=cell_index,
            same_shot_continuity_required=True,
            forbidden_layouts=[
                "storyboard_sheet",
                "collage",
                "split_screen",
                "multi_panel",
                "text_labels",
            ],
        )
    if slot_type == "shot_video_segment":
        details = result.detail_prompts
        return V2ShotVideoPromptPlan(
            summary_prompt=_summary_prompt(request, result),
            provider_prompt=_provider_prompt(request, result),
            negative_prompt=result.negative_prompt,
            negative_constraints=result.negative_constraints,
            reference_asset_ids=list(result.reference_asset_ids),
            quality_notes=list(result.quality_notes),
            warnings=_contract_warnings(result.warnings),
            storyboard_content=str(
                details.get("storyboard_content") or _provider_prompt(request, result)
            ),
            dialogue=str(details.get("dialogue") or "No spoken dialogue."),
            audio_description=str(
                details.get("audio_description")
                or "Use only production sound cues that support motion realism."
            ),
            voice_style=str(details.get("voice_style") or "Natural commercial voice style."),
            video_negative_constraints=str(
                details.get("video_negative_constraints")
                or result.negative_constraints
                or "No watermark. No subtitles. No identity drift."
            ),
            time_segments=list(
                details.get("time_segments")
                or [{"start_seconds": 0.0, "end_seconds": 5.0, "content": "Animate the shot."}]
            ),
            desired_duration_seconds=int(details.get("desired_duration_seconds") or 5),
            provider_duration_seconds=int(details.get("provider_duration_seconds") or 5),
            shot_cell_asset_ids=list(
                details.get("shot_cell_asset_ids") or result.reference_asset_ids
            ),
        )
    raise ValueError(f"Unsupported V2 prompt contract slot_type: {slot_type}")


def _base_payload(
    request: V2SpecialistPromptRequest,
    result: V2SpecialistPromptResult,
) -> dict[str, Any]:
    return {
        "summary_prompt": _summary_prompt(request, result),
        "specialist_prompt": result.specialist_prompt or _provider_prompt(request, result),
        "provider_prompt": _provider_prompt(request, result),
        "negative_prompt": result.negative_prompt,
        "negative_constraints": result.negative_constraints,
        "reference_asset_ids": list(result.reference_asset_ids),
        "quality_notes": list(result.quality_notes),
        "warnings": _contract_warnings(result.warnings),
    }


def _summary_prompt(
    request: V2SpecialistPromptRequest,
    result: V2SpecialistPromptResult,
) -> str:
    return (
        result.summary_prompt
        or request.summary_prompt
        or request.current_slot_prompt
        or result.provider_prompt
        or "Generate the requested media."
    )


def _provider_prompt(
    request: V2SpecialistPromptRequest,
    result: V2SpecialistPromptResult,
) -> str:
    return (
        result.provider_prompt
        or request.current_slot_prompt
        or request.summary_prompt
        or "Generate the requested media."
    )


def _contract_detail_prompts(contract_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in contract_payload.items() if key not in _COMMON_CONTRACT_FIELDS
    }


def _contract_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {str(key): str(value) for key, value in warning.items()}
        for warning in warnings
        if isinstance(warning, dict)
    ]


def _warning_dicts(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [warning for warning in warnings if isinstance(warning, dict)]


def _dedupe_warning_dicts(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for warning in warnings:
        key = json.dumps(warning, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(warning)
    return deduped


def _shot_cell_index(slot_type: str) -> int:
    try:
        value = int(slot_type.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        value = 1
    return min(max(value, 1), 4)


def _shot_cell_role(cell_index: int) -> str:
    return {
        1: "establishing",
        2: "action",
        3: "detail",
        4: "payoff",
    }[cell_index]
