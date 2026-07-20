from __future__ import annotations

import hashlib
import re
from typing import Any

from app.schemas.workflow_v2_storyboard_detail import (
    V2StoryboardDetailInput,
    V2StoryboardDetailPlan,
    V2StoryboardDetailQualityResult,
)

FORBIDDEN_CELL_LAYOUT_TERMS = (
    "storyboard sheet",
    "collage",
    "split screen",
    "split-screen",
    "multi-panel",
    "multi panel",
    "contact sheet",
    "text label",
    "text labels",
    "caption",
    "captions",
    "subtitle",
    "subtitles",
    "grid generation",
)
MUSIC_TERMS = (
    "bgm",
    "background music",
    "music",
    "soundtrack",
    "song",
    "lyrics",
    "vocals",
    "bgm generation",
)
RAW_PROMPT_WRAPPERS = (
    "professional storyboard detail for:",
    "dialogue direction for:",
    "audio atmosphere for:",
)
NEGATIVE_CONSTRAINT_TERMS = (
    "no watermark",
    "no subtitles",
    "no distorted product labels",
    "no identity drift",
    "no static pan-only motion",
)
SENSITIVE_KEYS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "raw_bytes",
    "raw_response",
    "file_content",
    "base64",
    "data_url",
)
FORBIDDEN_CROSS_SHOT_PROMPT_KEYS = (
    "cell_prompt",
    "cell_prompts",
    "provider_prompt",
    "video_provider_prompt",
)
FORBIDDEN_RAW_GRAPH_KEYS = (
    "graph",
    "workflow_graph",
    "workflow_nodes",
)
UNRELATED_PRODUCT_TERMS = (
    "detergent",
    "hand sanitizer",
    "milk carton",
    "milk bottle",
    "milk",
    "kitchen bottle",
)


class V2StoryboardDetailQualityError(RuntimeError):
    def __init__(
        self,
        failure_codes: list[str],
        *,
        violations: list[dict[str, Any]] | None = None,
    ) -> None:
        message = ", ".join(failure_codes) or "storyboard_detail_output_quality_failed"
        super().__init__(message)
        self.code = (
            "v2_storyboard_namespace_violation"
            if violations
            else "storyboard_detail_output_quality_failed"
        )
        self.failure_codes = failure_codes
        self.repair_details = {
            "failure_codes": failure_codes,
            "violations": violations or [],
        }


class V2StoryboardDetailQualityService:
    def validate_plan(
        self,
        plan: V2StoryboardDetailPlan,
        *,
        input_data: V2StoryboardDetailInput,
    ) -> None:
        namespace_failures, violations = _shot_namespace_failures(plan, input_data)
        result = self.evaluate_plan(plan, input_data=input_data)
        if result.status == "failed":
            raise V2StoryboardDetailQualityError(
                result.failure_codes,
                violations=violations if namespace_failures else None,
            )

    def evaluate_plan(
        self,
        plan: V2StoryboardDetailPlan,
        *,
        input_data: V2StoryboardDetailInput,
    ) -> V2StoryboardDetailQualityResult:
        failures: list[str] = []
        namespace_failures, _violations = _shot_namespace_failures(plan, input_data)
        failures.extend(namespace_failures)
        failures.extend(_four_cell_failures(plan))
        failures.extend(_cell_role_failures(plan))
        failures.extend(_cell_distinct_failures(plan))
        failures.extend(_cell_continuity_failures(plan, input_data))
        failures.extend(_cell_progression_failures(plan))
        failures.extend(_cell_layout_failures(plan))
        failures.extend(_video_field_failures(plan))
        failures.extend(_time_segment_failures(plan))
        failures.extend(_duration_failures(plan))
        failures.extend(_dialogue_failures(plan, input_data))
        failures.extend(_audio_policy_failures(plan))
        failures.extend(_negative_constraint_failures(plan))
        failures.extend(_raw_wrapper_failures(plan))
        failures.extend(_unrelated_product_failures(plan, input_data))
        failures.extend(_payload_safety_failures(plan, input_data))
        return V2StoryboardDetailQualityResult(
            status="failed" if failures else "passed",
            failure_codes=list(dict.fromkeys(failures)),
        )


def _shot_namespace_failures(
    plan: V2StoryboardDetailPlan,
    input_data: V2StoryboardDetailInput,
) -> tuple[list[str], list[dict[str, Any]]]:
    failures: list[str] = []
    violations: list[dict[str, Any]] = []
    if plan.shot_id != input_data.shot_id:
        failures.append("shot_id_namespace")
        violations.append({"path": "$.plan.shot_id", "reason": "current_shot_mismatch"})
    if plan.shot_index != input_data.shot_index:
        failures.append("shot_index_namespace")
        violations.append({"path": "$.plan.shot_index", "reason": "current_shot_mismatch"})

    expected_slot_ids = [f"{input_data.shot_id}:shot_cell_{index}" for index in range(1, 5)]
    if plan.video_detail.required_shot_cell_slot_ids != expected_slot_ids:
        failures.append("shot_cell_slot_namespace")
        violations.append(
            {
                "path": "$.plan.video_detail.required_shot_cell_slot_ids",
                "reason": "current_shot_cells_required",
            }
        )
    context_failures, context_violations = _context_isolation_failures(
        plan,
        input_data,
    )
    failures.extend(context_failures)
    violations.extend(context_violations)
    return failures, violations


def _context_isolation_failures(
    plan: V2StoryboardDetailPlan,
    input_data: V2StoryboardDetailInput,
) -> tuple[list[str], list[dict[str, Any]]]:
    failures: list[str] = []
    violations = _forbidden_context_paths(
        input_data.model_dump(mode="json"),
        current_shot_id=input_data.shot_id,
        prefix="$.input",
    )
    failures.extend(str(item["code"]) for item in violations)

    references_by_asset_id = {
        str(reference.get("asset_id")): reference
        for reference in input_data.selected_reference_summaries
        if str(reference.get("asset_id") or "").strip()
    }
    allowed_item_ids = _script_shot_reference_item_ids(input_data.script_shot)
    invalid_item_ids = [
        item_id for item_id in plan.reference_item_ids if item_id not in allowed_item_ids
    ]
    if invalid_item_ids:
        failures.append("current_shot_reference_items")
        violations.append(
            {
                "code": "current_shot_reference_items",
                "path": "$.plan.reference_item_ids",
                "reason": "reference_item_not_in_current_script_shot",
                "fingerprints": [_fingerprint(item_id) for item_id in invalid_item_ids],
            }
        )

    invalid_plan_assets = _invalid_current_shot_reference_assets(
        plan.reference_asset_ids,
        references_by_asset_id,
        allowed_item_ids,
    )
    if invalid_plan_assets:
        failures.append("current_shot_reference_assets")
        violations.append(
            {
                "code": "current_shot_reference_assets",
                "path": "$.plan.reference_asset_ids",
                "reason": "reference_asset_owner_not_in_current_script_shot",
                "fingerprints": [_fingerprint(asset_id) for asset_id in invalid_plan_assets],
            }
        )

    invalid_cell_assets = list(
        dict.fromkeys(
            asset_id
            for cell in plan.cell_prompts
            for asset_id in _invalid_current_shot_reference_assets(
                cell.required_reference_asset_ids,
                references_by_asset_id,
                allowed_item_ids,
            )
        )
    )
    if invalid_cell_assets:
        failures.append("cell_reference_asset_ownership")
        violations.append(
            {
                "code": "cell_reference_asset_ownership",
                "path": "$.plan.cell_prompts[*].required_reference_asset_ids",
                "reason": "cell_reference_owner_not_in_current_script_shot",
                "fingerprints": [_fingerprint(asset_id) for asset_id in invalid_cell_assets],
            }
        )

    for asset_id in plan.video_detail.required_shot_cell_asset_ids:
        reference = references_by_asset_id.get(asset_id)
        if not _is_current_shot_cell_reference(reference, input_data.shot_id):
            failures.append("sibling_cell_asset")
            violations.append(
                {
                    "code": "sibling_cell_asset",
                    "path": "$.plan.video_detail.required_shot_cell_asset_ids",
                    "reason": "cell_asset_owner_not_current_shot",
                    "fingerprint": _fingerprint(asset_id),
                }
            )
    return list(dict.fromkeys(failures)), violations


def _script_shot_reference_item_ids(script_shot: dict[str, Any]) -> set[str]:
    item_ids: list[str] = []
    for key in ("product_ids", "character_ids", "scene_ids", "reference_item_ids"):
        value = script_shot.get(key)
        if isinstance(value, list):
            item_ids.extend(str(item).strip() for item in value if str(item).strip())
    scene_id = str(script_shot.get("scene_id") or "").strip()
    if scene_id:
        item_ids.append(scene_id)
    return set(item_ids)


def _invalid_current_shot_reference_assets(
    asset_ids: list[str],
    references_by_asset_id: dict[str, dict[str, Any]],
    allowed_item_ids: set[str],
) -> list[str]:
    invalid: list[str] = []
    for asset_id in asset_ids:
        reference = references_by_asset_id.get(asset_id)
        owner_item_id = (
            str(reference.get("owner_item_id") or "").strip() if isinstance(reference, dict) else ""
        )
        if not owner_item_id or owner_item_id not in allowed_item_ids:
            invalid.append(asset_id)
    return list(dict.fromkeys(invalid))


def _forbidden_context_paths(
    value: Any,
    *,
    current_shot_id: str,
    prefix: str,
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if _looks_like_cell_reference(value) and not _is_current_shot_cell_reference(
            value,
            current_shot_id,
        ):
            violations.append(
                {
                    "code": "sibling_cell_asset",
                    "path": prefix,
                    "reason": "cell_asset_owner_not_current_shot",
                }
            )
        for key, item in value.items():
            key_text = str(key).lower()
            path = f"{prefix}.{key}"
            if any(
                key_text == forbidden_key or key_text.endswith(f"_{forbidden_key}")
                for forbidden_key in FORBIDDEN_CROSS_SHOT_PROMPT_KEYS
            ):
                violations.append(
                    {
                        "code": "sibling_full_prompt",
                        "path": path,
                        "reason": "full_prompt_not_allowed_in_detail_input",
                        "fingerprint": _fingerprint(item),
                    }
                )
                continue
            if key_text in FORBIDDEN_RAW_GRAPH_KEYS:
                violations.append(
                    {
                        "code": "raw_workflow_graph",
                        "path": path,
                        "reason": "raw_graph_not_allowed_in_detail_input",
                    }
                )
                continue
            violations.extend(
                _forbidden_context_paths(
                    item,
                    current_shot_id=current_shot_id,
                    prefix=path,
                )
            )
        return violations
    if isinstance(value, list):
        for index, item in enumerate(value):
            violations.extend(
                _forbidden_context_paths(
                    item,
                    current_shot_id=current_shot_id,
                    prefix=f"{prefix}[{index}]",
                )
            )
        return violations
    if isinstance(value, str):
        current_prefix = f"{current_shot_id}:shot_cell_"
        for slot_id in re.findall(r"[A-Za-z0-9._-]+:shot_cell_[1-4]", value):
            if not slot_id.startswith(current_prefix):
                violations.append(
                    {
                        "code": "sibling_slot_id",
                        "path": prefix,
                        "reason": "slot_id_not_in_current_shot",
                        "fingerprint": _fingerprint(slot_id),
                    }
                )
    return violations


def _looks_like_cell_reference(reference: dict[str, Any]) -> bool:
    slot_type = str(reference.get("slot_type") or "")
    source_slot_id = str(reference.get("source_slot_id") or "")
    return slot_type.startswith("shot_cell_") or ":shot_cell_" in source_slot_id


def _is_current_shot_cell_reference(
    reference: dict[str, Any] | None,
    current_shot_id: str,
) -> bool:
    if not isinstance(reference, dict):
        return False
    owner_item_id = str(reference.get("owner_item_id") or "").strip()
    source_slot_id = str(reference.get("source_slot_id") or "").strip()
    slot_type = str(reference.get("slot_type") or "").strip()
    if not slot_type.startswith("shot_cell_"):
        return False
    if owner_item_id != current_shot_id:
        return False
    return not source_slot_id or source_slot_id.startswith(f"{current_shot_id}:shot_cell_")


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _four_cell_failures(plan: V2StoryboardDetailPlan) -> list[str]:
    if len(plan.cell_prompts) != 4:
        return ["four_cell_prompts_present"]
    if [cell.slot_type for cell in plan.cell_prompts] != [
        "shot_cell_1",
        "shot_cell_2",
        "shot_cell_3",
        "shot_cell_4",
    ]:
        return ["four_cell_prompts_present"]
    return []


def _cell_role_failures(plan: V2StoryboardDetailPlan) -> list[str]:
    roles = [cell.cell_role for cell in plan.cell_prompts]
    if roles != ["establishing", "action", "detail", "payoff"]:
        return ["cell_roles_present"]
    return []


def _cell_distinct_failures(plan: V2StoryboardDetailPlan) -> list[str]:
    normalized = [_normalize_text(cell.provider_prompt) for cell in plan.cell_prompts]
    if len(set(normalized)) < 4:
        return ["cell_prompts_are_distinct"]
    similarities = [
        _token_similarity(left, right)
        for index, left in enumerate(normalized)
        for right in normalized[index + 1 :]
    ]
    if similarities and all(score >= 0.95 for score in similarities):
        return ["cell_prompts_are_distinct"]
    return []


def _cell_continuity_failures(
    plan: V2StoryboardDetailPlan,
    input_data: V2StoryboardDetailInput,
) -> list[str]:
    combined_reference_text = _normalize_text(
        " ".join(
            [
                input_data.shot_summary_prompt,
                _summary_text(input_data.product_brief_summaries),
                _summary_text(input_data.character_brief_summaries),
                _summary_text(input_data.scene_brief_summaries),
            ]
        )
    )
    continuity_terms = (
        "product",
        "character",
        "scene",
        "identity",
        "style",
        "lighting",
        "time",
    )
    for cell in plan.cell_prompts:
        prompt = _normalize_text(cell.provider_prompt)
        if not all(term in prompt for term in continuity_terms[:4]):
            return ["cell_prompts_preserve_continuity"]
        if combined_reference_text and not _shares_meaningful_token(
            prompt, combined_reference_text
        ):
            return ["cell_prompts_preserve_continuity"]
    return []


def _cell_progression_failures(plan: V2StoryboardDetailPlan) -> list[str]:
    prompts = [_normalize_text(cell.provider_prompt) for cell in plan.cell_prompts]
    progression_terms = (
        "wide",
        "medium",
        "close",
        "hero",
        "establish",
        "grip",
        "twist",
        "peak",
        "present",
        "payoff",
        "emotion",
        "interaction",
    )
    has_progression = sum(any(term in prompt for term in progression_terms) for prompt in prompts)
    if has_progression < 3:
        return ["cell_prompts_advance_action"]
    if (
        len(
            {
                re.sub(
                    r"\\b(establishing|establish|action|detail|payoff|frame|keyframe)\\b",
                    "",
                    p,
                )
                for p in prompts
            }
        )
        < 3
    ):
        return ["cell_prompts_advance_action"]
    return []


def _cell_layout_failures(plan: V2StoryboardDetailPlan) -> list[str]:
    for cell in plan.cell_prompts:
        if _contains_positive_term(cell.provider_prompt, FORBIDDEN_CELL_LAYOUT_TERMS):
            return ["cell_prompts_do_not_request_grids_or_sheets"]
    return []


def _video_field_failures(plan: V2StoryboardDetailPlan) -> list[str]:
    video = plan.video_detail
    required = [
        video.provider_prompt,
        video.storyboard_content,
        video.dialogue,
        video.audio_description,
        video.voice_style,
        video.video_negative_constraints,
    ]
    if not all(value.strip() for value in required) or not video.time_segments:
        return ["video_detail_fields_present"]
    return []


def _time_segment_failures(plan: V2StoryboardDetailPlan) -> list[str]:
    segments = plan.video_detail.time_segments
    if not segments or abs(segments[0].start_seconds - 0.0) > 0.001:
        return ["video_time_segments_valid"]
    previous_end = 0.0
    for segment in segments:
        if segment.start_seconds < previous_end - 0.001:
            return ["video_time_segments_valid"]
        if segment.end_seconds <= segment.start_seconds:
            return ["video_time_segments_valid"]
        text = segment.content.lower()
        if not any(
            term in text for term in ("camera", "framing", "close", "wide", "medium", "hero")
        ):
            return ["video_time_segments_valid"]
        if not any(
            term in text
            for term in (
                "action",
                "move",
                "twist",
                "open",
                "present",
                "gesture",
                "reveal",
                "establish",
                "capture",
                "frame",
            )
        ):
            return ["video_time_segments_valid"]
        previous_end = segment.end_seconds
    if abs(segments[-1].end_seconds - float(plan.provider_duration_seconds)) > 0.01:
        return ["video_time_segments_valid"]
    return []


def _duration_failures(plan: V2StoryboardDetailPlan) -> list[str]:
    if plan.provider_duration_seconds not in {5, 10}:
        return ["video_uses_supported_duration"]
    if plan.video_detail.provider_duration_seconds != plan.provider_duration_seconds:
        return ["video_uses_supported_duration"]
    return []


def _dialogue_failures(
    plan: V2StoryboardDetailPlan,
    input_data: V2StoryboardDetailInput,
) -> list[str]:
    narration = str(input_data.script_shot.get("narration") or "").strip()
    dialogue = plan.video_detail.dialogue.strip()
    if narration:
        return [] if narration in dialogue else ["video_dialogue_policy_valid"]
    if "no spoken dialogue" not in dialogue.lower():
        return ["video_dialogue_policy_valid"]
    return []


def _audio_policy_failures(plan: V2StoryboardDetailPlan) -> list[str]:
    combined = " ".join(
        [
            plan.video_detail.provider_prompt,
            plan.video_detail.audio_description,
            plan.video_detail.storyboard_content,
        ]
    )
    if _contains_positive_term(combined, MUSIC_TERMS):
        return ["video_audio_policy_valid"]
    return []


def _negative_constraint_failures(plan: V2StoryboardDetailPlan) -> list[str]:
    lower = plan.video_detail.video_negative_constraints.lower()
    if not all(term in lower for term in NEGATIVE_CONSTRAINT_TERMS):
        return ["video_negative_constraints_present"]
    return []


def _raw_wrapper_failures(plan: V2StoryboardDetailPlan) -> list[str]:
    values = [cell.provider_prompt for cell in plan.cell_prompts] + [
        plan.video_detail.provider_prompt,
        plan.video_detail.storyboard_content,
        plan.video_detail.dialogue,
        plan.video_detail.audio_description,
    ]
    combined = "\n".join(values).lower()
    if any(wrapper in combined for wrapper in RAW_PROMPT_WRAPPERS):
        return ["no_raw_prompt_wrapper"]
    return []


def _unrelated_product_failures(
    plan: V2StoryboardDetailPlan,
    input_data: V2StoryboardDetailInput,
) -> list[str]:
    output_text = _normalize_text(
        " ".join(
            [
                *(cell.provider_prompt for cell in plan.cell_prompts),
                plan.video_detail.provider_prompt,
                plan.video_detail.storyboard_content,
                plan.video_detail.dialogue,
                plan.video_detail.audio_description,
                plan.video_detail.voice_style,
            ]
        )
    )
    input_text = _normalize_text(str(input_data.model_dump(mode="json")))
    for term in UNRELATED_PRODUCT_TERMS:
        normalized_term = _normalize_text(term)
        if normalized_term in output_text and normalized_term not in input_text:
            return ["storyboard_detail_no_unrelated_products"]
    return []


def _payload_safety_failures(
    plan: V2StoryboardDetailPlan,
    input_data: V2StoryboardDetailInput,
) -> list[str]:
    unsafe_paths = [
        *_unsafe_payload_paths(plan.model_dump(mode="json"), prefix="$.plan"),
        *_unsafe_payload_paths(input_data.model_dump(mode="json"), prefix="$.input"),
    ]
    return ["payload_safety"] if unsafe_paths else []


def _summary_text(items: list[dict[str, Any]]) -> str:
    return " ".join(
        str(item.get("summary") or item.get("description") or item.get("display_name") or "")
        for item in items
    )


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value.lower())).strip()


def _token_similarity(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _shares_meaningful_token(left: str, right: str) -> bool:
    stop = {
        "the",
        "and",
        "with",
        "same",
        "identity",
        "style",
        "lighting",
        "scene",
        "product",
        "character",
    }
    left_tokens = {token for token in left.split() if len(token) > 3 and token not in stop}
    right_tokens = {token for token in right.split() if len(token) > 3 and token not in stop}
    return bool(left_tokens & right_tokens)


def _contains_positive_term(value: str, terms: tuple[str, ...]) -> bool:
    lower = value.lower()
    for term in terms:
        start = lower.find(term)
        while start >= 0:
            prefix = lower[max(0, start - 24) : start]
            if not re.search(r"\b(no|without|avoid|exclude|not|never)\b", prefix):
                return True
            start = lower.find(term, start + len(term))
    return False


def _unsafe_payload_paths(value: Any, *, prefix: str = "$") -> list[str]:
    unsafe: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            path = f"{prefix}.{key}"
            if any(sensitive in key_text for sensitive in SENSITIVE_KEYS):
                unsafe.append(path)
                continue
            unsafe.extend(_unsafe_payload_paths(item, prefix=path))
        return unsafe
    if isinstance(value, list):
        for index, item in enumerate(value):
            unsafe.extend(_unsafe_payload_paths(item, prefix=f"{prefix}[{index}]"))
        return unsafe
    if isinstance(value, str):
        normalized = value.strip().lower()
        if (
            normalized.startswith("data:")
            or "base64," in normalized
            or "-----begin" in normalized
            or len(value) > 20_000
        ):
            unsafe.append(prefix)
    return unsafe
