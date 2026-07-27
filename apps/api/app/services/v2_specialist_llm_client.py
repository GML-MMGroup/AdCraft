from __future__ import annotations

import re
from typing import Any, cast

from app.core.config import Settings
from app.schemas.workflow_v2 import V2SpecialistPromptRequest, V2SpecialistPromptResult
from app.schemas.workflow_v2_prompt_contracts import (
    V2PromptContractModel,
    prompt_contract_model_for_slot,
    prompt_contract_name_for_slot,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_prompt_contract_adapter import (
    prompt_contract_from_specialist_result,
    specialist_result_from_prompt_contract,
)
from app.services.v2_prompt_contract_quality import validate_prompt_contract
from app.services.v2_specialist_configs import V2SpecialistConfig
from app.services.v2_structured_generation_runtime import (
    StructuredGenerationRuntime,
    StructuredGenerationRuntimeError,
    StructuredGenerationSpec,
)


class V2SpecialistLLMClientError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class V2SpecialistLLMClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._structured_runtime = StructuredGenerationRuntime(settings=settings)

    def materialize(
        self,
        request: V2SpecialistPromptRequest,
        config: V2SpecialistConfig,
    ) -> V2SpecialistPromptResult:
        if not self._settings.llm_api_key or not self._settings.llm_base_url:
            raise V2SpecialistLLMClientError(
                "real_specialist_unavailable",
                "LLM API key and base URL are required for real specialist materialization.",
            )
        slot_type = str(request.target.get("slot_type") or "")
        try:
            output_model = prompt_contract_model_for_slot(slot_type)
        except ValueError as exc:
            raise V2SpecialistLLMClientError(
                "specialist_output_schema_invalid",
                str(exc),
            ) from exc

        payload = _safe_llm_payload(request, config, slot_type=slot_type)
        authoritative_reference_ids = _authoritative_reference_ids(request)
        allowed_reference_ids = set(authoritative_reference_ids)
        try:
            structured = self._structured_runtime.run(
                StructuredGenerationSpec(
                    stage_name="specialist_materializer",
                    contract_name=prompt_contract_name_for_slot(slot_type),
                    model_id=config.model_id,
                    system_prompt="",
                    input_payload=payload,
                    output_model=output_model,
                    output_normalizer=lambda contract: _canonicalize_prompt_contract(
                        cast(V2PromptContractModel, contract),
                        request=request,
                        slot_type=slot_type,
                        authoritative_reference_ids=authoritative_reference_ids,
                    ),
                    quality_validator=lambda contract: validate_prompt_contract(
                        cast(V2PromptContractModel, contract),
                        slot_type=slot_type,
                        required_reference_asset_ids=_required_reference_ids(
                            slot_type,
                            allowed_reference_ids,
                        ),
                    ),
                )
            )
        except StructuredGenerationRuntimeError as exc:
            raise V2SpecialistLLMClientError(
                _client_error_code(exc.code),
                str(exc),
            ) from exc

        contract = cast(V2PromptContractModel, structured.output)
        result = specialist_result_from_prompt_contract(
            contract,
            slot_type=slot_type,
            materializer_mode="real",
            model_id=config.model_id,
        )
        _validate_reference_ids(allowed_reference_ids, result)
        return result


def _safe_llm_payload(
    request: V2SpecialistPromptRequest,
    config: V2SpecialistConfig,
    *,
    slot_type: str,
) -> dict[str, Any]:
    payload = {
        "specialist": config.specialist,
        "display_name": config.display_name,
        "allowed_slot_types": sorted(config.allowed_slot_types),
        "skill_pack_ids": list(config.skill_pack_ids),
        "slot_type": slot_type,
        "prompt_contract_name": prompt_contract_name_for_slot(slot_type),
        "request": request.model_dump(mode="json"),
    }
    return sanitize_context_for_llm_text(payload)


def _authoritative_reference_ids(request: V2SpecialistPromptRequest) -> list[str]:
    return list(
        dict.fromkeys(
            str(summary.get("asset_id"))
            for summary in [
                *request.reference_asset_summaries,
                *request.dependency_asset_summaries,
            ]
            if isinstance(summary, dict) and summary.get("asset_id")
        )
    )


def _canonicalize_prompt_contract(
    contract: V2PromptContractModel,
    *,
    request: V2SpecialistPromptRequest,
    slot_type: str,
    authoritative_reference_ids: list[str],
) -> V2PromptContractModel:
    original_payload = contract.model_dump(mode="json")
    result = specialist_result_from_prompt_contract(
        contract,
        slot_type=slot_type,
        materializer_mode="real",
        model_id=None,
    )
    details = dict(result.detail_prompts)
    for key in ("prompt_contract", "prompt_contract_name", "prompt_contract_version"):
        details.pop(key, None)
    updates: dict[str, Any] = {
        "detail_prompts": details,
        "reference_asset_ids": authoritative_reference_ids,
        "quality_notes": list(getattr(contract, "quality_notes", [])),
    }

    if slot_type.startswith("shot_cell_"):
        provider_prompt = str(result.provider_prompt or "").strip()
        if not _has_single_keyframe_intent(provider_prompt):
            updates["provider_prompt"] = (
                f"{provider_prompt} Generate one single full-frame keyframe only."
            ).strip()

    if slot_type == "shot_video_segment":
        details["shot_cell_asset_ids"] = authoritative_reference_ids
        details["audio_description"] = _production_audio_description(
            details.get("audio_description")
        )
        details["video_negative_constraints"] = (
            _optional_score_safe_text(details.get("video_negative_constraints"))
            or "No watermark. No subtitles. Preserve product, character, and scene identity."
        )
        updates["detail_prompts"] = details
        updates["provider_prompt"] = (
            _optional_score_safe_text(result.provider_prompt)
            or str(
                details.get("storyboard_content")
                or request.current_slot_prompt
                or request.summary_prompt
                or "Animate the selected storyboard keyframes."
            ).strip()
        )
        updates["negative_constraints"] = _optional_score_safe_text(result.negative_constraints)

    result = result.model_copy(update=updates)
    canonical = prompt_contract_from_specialist_result(
        request,
        result,
        slot_type=slot_type,
    )
    if canonical.model_dump(mode="json") == original_payload:
        return canonical

    warning = {
        "code": "authoritative_prompt_contract_fields_canonicalized",
        "message": "Backend-owned slot fields were canonicalized before prompt quality validation.",
    }
    result = result.model_copy(
        update={
            "warnings": _dedupe_warnings([*result.warnings, warning]),
            "quality_notes": list(
                dict.fromkeys(
                    [
                        *result.quality_notes,
                        "authoritative_slot_fields_canonicalized",
                    ]
                )
            ),
        }
    )
    return prompt_contract_from_specialist_result(request, result, slot_type=slot_type)


def _has_single_keyframe_intent(value: str) -> bool:
    normalized = value.lower()
    return any(
        phrase in normalized
        for phrase in (
            "single keyframe",
            "one keyframe",
            "single full-frame",
            "full-frame keyframe",
            "single frame",
            "one frame",
        )
    )


_SCORE_TERM_PATTERN = re.compile(
    r"\b(?:bgm|music|soundtrack|songs?|lyrics|vocals?)\b",
    re.IGNORECASE,
)


def _remove_score_requests(value: str) -> str:
    sentences = re.split(r"(?<=[.!?])(?:\s+|$)|[\r\n]+", value.strip())
    return " ".join(
        sentence.strip()
        for sentence in sentences
        if sentence.strip() and not _SCORE_TERM_PATTERN.search(sentence)
    )


def _optional_score_safe_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return _remove_score_requests(value) or None


def _production_audio_description(value: Any) -> str:
    audio_description = _optional_score_safe_text(value)
    if not audio_description:
        audio_description = (
            "Use synchronized environment ambience, dialogue when provided, "
            "movement, and action sound effects."
        )
    policy = "Use production audio only; exclude a dedicated score."
    if policy.lower() not in audio_description.lower():
        audio_description = f"{audio_description} {policy}"
    return audio_description


def _dedupe_warnings(warnings: list[Any]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for warning in warnings:
        if not isinstance(warning, dict):
            continue
        normalized = {str(key): str(value) for key, value in warning.items()}
        identity = tuple(sorted(normalized.items()))
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(normalized)
    return deduped


def _required_reference_ids(slot_type: str, allowed_reference_ids: set[str]) -> list[str]:
    if slot_type in {
        "product_multi_view_grid",
        "character_three_view",
        "scene_multi_view_grid",
        "shot_video_segment",
    }:
        return sorted(allowed_reference_ids)
    return []


def _validate_reference_ids(
    allowed_reference_ids: set[str],
    result: V2SpecialistPromptResult,
) -> None:
    unknown_ids = [
        asset_id for asset_id in result.reference_asset_ids if asset_id not in allowed_reference_ids
    ]
    if unknown_ids:
        raise V2SpecialistLLMClientError(
            "specialist_target_mismatch",
            f"Specialist returned unknown reference asset ids: {unknown_ids}",
        )


def _client_error_code(code: str) -> str:
    return {
        "structured_llm_unavailable": "real_specialist_unavailable",
        "structured_llm_call_failed": "specialist_llm_call_failed",
        "structured_output_invalid_json": "specialist_output_invalid_json",
        "agent_structured_output_invalid": "specialist_output_invalid_json",
        "structured_generation_schema_failed": "specialist_output_invalid_json",
        "structured_output_schema_invalid": "specialist_output_schema_invalid",
        "structured_output_quality_failed": "specialist_output_quality_failed",
    }.get(code, "specialist_llm_call_failed")
