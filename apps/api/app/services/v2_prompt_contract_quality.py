from __future__ import annotations

import re
from collections.abc import Iterable

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
)


class V2PromptContractQualityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_prompt_contract(
    contract: V2PromptContractModel,
    *,
    slot_type: str,
    required_reference_asset_ids: Iterable[str] | None = None,
) -> None:
    required_reference_asset_ids = list(required_reference_asset_ids or [])
    if isinstance(contract, V2CharacterMainPromptPlan):
        _validate_character_main(contract)
    elif isinstance(contract, V2CharacterThreeViewPromptPlan):
        _validate_character_three_view(contract, required_reference_asset_ids)
    elif isinstance(contract, V2SceneMainPromptPlan):
        _validate_scene_main(contract)
    elif isinstance(contract, V2SceneMultiViewPromptPlan):
        _validate_scene_multi_view(contract, required_reference_asset_ids)
    elif isinstance(contract, V2ShotCellPromptPlan):
        _validate_shot_cell(contract, slot_type)
    elif isinstance(contract, V2ShotVideoPromptPlan):
        _validate_shot_video(contract, required_reference_asset_ids)
    elif isinstance(contract, V2ProductMainPromptPlan):
        _validate_product_main(contract)
    elif isinstance(contract, V2ProductMultiViewPromptPlan):
        _validate_product_multi_view(contract, required_reference_asset_ids)


def validate_shot_cell_prompt_distinctness(
    contracts: list[V2ShotCellPromptPlan],
) -> None:
    normalized = [_normalize_prompt(contract.provider_prompt) for contract in contracts]
    if len(normalized) >= 2 and len(set(normalized)) == 1:
        _raise("shot_cell_prompts_must_be_distinct")


def _validate_product_main(contract: V2ProductMainPromptPlan) -> None:
    text = _contract_text(contract)
    _reject_any(
        text,
        [
            "multi view",
            "multi-view",
            "grid",
            "contact sheet",
            "collage",
            "four views",
            "2x2",
        ],
        "product_main_must_be_single_product",
    )
    _require_any(
        text,
        ["single product", "main product", "hero product", "product reference"],
        "product_main_requires_single_product_intent",
    )


def _validate_product_multi_view(
    contract: V2ProductMultiViewPromptPlan,
    required_reference_asset_ids: list[str],
) -> None:
    text = _contract_text(contract)
    _require_any(text, ["2x2", "four views", "4 views"], "product_grid_requires_2x2")
    _require_any(text, ["same product", "same item"], "product_grid_requires_same_product")
    _require_references(contract.reference_asset_ids, required_reference_asset_ids)


def _validate_character_main(contract: V2CharacterMainPromptPlan) -> None:
    text = _contract_text(contract)
    _reject_any(
        text,
        [
            "turnaround",
            "three view",
            "three-view",
            "front side back",
            "front, side, and back",
            "multi view",
            "multi-view",
            "grid",
            "sheet",
            "contact sheet",
            "collage",
        ],
        "character_main_must_not_request_turnaround",
    )
    _require_any(
        text,
        ["single character", "main character", "hero character", "character reference"],
        "character_main_requires_single_reference_intent",
    )


def _validate_character_three_view(
    contract: V2CharacterThreeViewPromptPlan,
    required_reference_asset_ids: list[str],
) -> None:
    text = _contract_text(contract)
    for term in ("front", "side", "back"):
        if term not in text:
            _raise("character_three_view_requires_front_side_back")
    _reject_any(
        text,
        ["unrelated character", "different characters", "multiple identities"],
        "character_three_view_requires_same_identity",
    )
    _require_references(contract.reference_asset_ids, required_reference_asset_ids)


def _validate_scene_main(contract: V2SceneMainPromptPlan) -> None:
    text = _contract_text(contract)
    _reject_any(
        text,
        [
            "multi view",
            "multi-view",
            "grid",
            "collage",
            "storyboard sheet",
            "split screen",
            "split-screen",
            "four views",
            "2x2",
        ],
        "scene_main_must_be_single_scene",
    )
    _require_any(
        text,
        [
            "environment",
            "location",
            "layout",
            "lighting",
            "material",
            "architecture",
            "interior",
            "exterior",
            "street",
            "room",
        ],
        "scene_main_requires_concrete_environment_cues",
    )


def _validate_scene_multi_view(
    contract: V2SceneMultiViewPromptPlan,
    required_reference_asset_ids: list[str],
) -> None:
    text = _contract_text(contract)
    _require_any(text, ["2x2", "four views", "4 views"], "scene_grid_requires_2x2")
    _require_any(
        text,
        ["same location", "same environment", "same scene"],
        "scene_grid_requires_same_location",
    )
    _require_references(contract.reference_asset_ids, required_reference_asset_ids)


def _validate_shot_cell(contract: V2ShotCellPromptPlan, slot_type: str) -> None:
    text = _contract_text(contract)
    expected_index = _expected_shot_cell_index(slot_type)
    if expected_index is not None and contract.cell_index != expected_index:
        _raise("shot_cell_index_mismatch")
    _reject_any(
        text,
        [
            "storyboard sheet",
            "collage",
            "split screen",
            "split-screen",
            "multi panel",
            "multi-panel",
            "text label",
            "text labels",
            "caption",
            "subtitles",
        ],
        "shot_cell_must_be_single_keyframe",
    )
    _require_any(
        text,
        [
            "single keyframe",
            "one keyframe",
            "single full-frame",
            "full-frame keyframe",
            "single frame",
            "one frame",
        ],
        "shot_cell_requires_single_keyframe_intent",
    )


def _validate_shot_video(
    contract: V2ShotVideoPromptPlan,
    required_reference_asset_ids: list[str],
) -> None:
    text = _contract_text(contract)
    audio_text = _normalized(
        " ".join(
            [
                contract.provider_prompt,
                contract.audio_description,
                contract.video_negative_constraints,
            ]
        )
    )
    _reject_any(
        audio_text,
        ["bgm", "music", "soundtrack", "song", "lyrics", "vocals"],
        "shot_video_must_not_request_music",
    )
    constraints = _normalized(contract.video_negative_constraints)
    _require_any(
        constraints, ["no watermark", "without watermark"], "shot_video_requires_no_watermark"
    )
    _require_any(
        constraints, ["no subtitles", "without subtitles"], "shot_video_requires_no_subtitles"
    )
    if len(contract.shot_cell_asset_ids) != 4:
        _raise("shot_video_requires_four_shot_cells")
    _require_references(contract.reference_asset_ids, contract.shot_cell_asset_ids)
    _require_references(contract.reference_asset_ids, required_reference_asset_ids)
    _validate_time_segments(contract)
    _reject_any(
        text,
        ["storyboard sheet", "collage", "split screen", "split-screen", "multi panel"],
        "shot_video_must_use_selected_cells_not_storyboard_sheet",
    )


def _validate_time_segments(contract: V2ShotVideoPromptPlan) -> None:
    segments = sorted(contract.time_segments, key=lambda item: item.start_seconds)
    if segments[0].start_seconds != 0:
        _raise("shot_video_segments_must_start_at_zero")
    previous_end = 0.0
    for segment in segments:
        if segment.start_seconds < previous_end:
            _raise("shot_video_segments_must_not_overlap")
        if segment.end_seconds <= segment.start_seconds:
            _raise("shot_video_segments_must_have_positive_duration")
        previous_end = segment.end_seconds
    if abs(previous_end - contract.provider_duration_seconds) > 0.001:
        _raise("shot_video_segments_must_cover_provider_duration")


def _require_references(
    actual_reference_asset_ids: list[str],
    required_reference_asset_ids: list[str],
) -> None:
    missing = [
        reference_id
        for reference_id in required_reference_asset_ids
        if reference_id not in actual_reference_asset_ids
    ]
    if missing:
        _raise("prompt_contract_missing_required_references")


def _require_any(text: str, terms: list[str], code: str) -> None:
    if not any(term in text for term in terms):
        _raise(code)


def _reject_any(text: str, terms: list[str], code: str) -> None:
    if any(_contains_unnegated_term(text, term) for term in terms):
        _raise(code)


def _contract_text(contract: object) -> str:
    values: list[str] = []
    for field_name in (
        "summary_prompt",
        "specialist_prompt",
        "provider_prompt",
        "negative_prompt",
        "negative_constraints",
        "storyboard_content",
        "dialogue",
        "audio_description",
        "voice_style",
        "video_negative_constraints",
    ):
        value = getattr(contract, field_name, None)
        if isinstance(value, str):
            values.append(value)
    return _normalized(" ".join(values))


def _normalize_prompt(value: str) -> str:
    return _normalized(value)


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _contains_unnegated_term(text: str, term: str) -> bool:
    normalized_term = _normalized(term)
    start = 0
    while True:
        index = text.find(normalized_term, start)
        if index < 0:
            return False
        prefix = text[max(0, index - 24) : index].strip()
        if not _has_negation(prefix):
            return True
        start = index + len(normalized_term)


def _has_negation(prefix: str) -> bool:
    words = re.findall(r"[a-z']+", prefix.lower())
    if not words:
        return False
    tail = words[-5:]
    joined_tail = " ".join(tail)
    return (
        "no" in tail
        or "not" in tail
        or "without" in tail
        or "never" in tail
        or "do not" in joined_tail
        or "don't" in tail
    )


def _expected_shot_cell_index(slot_type: str) -> int | None:
    match = re.fullmatch(r"shot_cell_([1-4])", slot_type)
    return int(match.group(1)) if match else None


def _raise(detail_code: str) -> None:
    raise V2PromptContractQualityError(
        "structured_output_quality_failed",
        detail_code,
    )
