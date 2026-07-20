from __future__ import annotations

from typing import Any, cast

from app.core.config import Settings
from app.schemas.workflow_v2 import V2SpecialistPromptRequest, V2SpecialistPromptResult
from app.schemas.workflow_v2_prompt_contracts import (
    V2PromptContractModel,
    prompt_contract_model_for_slot,
    prompt_contract_name_for_slot,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_high_risk_prompt_renderer import V2HighRiskPromptRenderer
from app.services.v2_prompt_contract_adapter import (
    specialist_result_from_prompt_contract,
)
from app.services.v2_prompt_contract_quality import validate_prompt_contract
from app.services.v2_specialist_configs import V2SpecialistConfig
from app.services.v2_structured_llm import V2StructuredLLMClient, V2StructuredLLMError


class V2SpecialistLLMClientError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class V2SpecialistLLMClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._structured_llm = V2StructuredLLMClient(settings)

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
        allowed_reference_ids = _allowed_reference_ids(request)
        try:
            structured = self._structured_llm.generate(
                model_id=config.model_id,
                system_prompt=_system_prompt(config, slot_type),
                user_payload=payload,
                output_model=output_model,
                contract_name=prompt_contract_name_for_slot(slot_type),
                quality_validator=lambda contract: validate_prompt_contract(
                    cast(V2PromptContractModel, contract),
                    slot_type=slot_type,
                    required_reference_asset_ids=_required_reference_ids(
                        slot_type,
                        allowed_reference_ids,
                    ),
                ),
                stage_name="specialist_materializer",
            )
        except V2StructuredLLMError as exc:
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


def _system_prompt(config: V2SpecialistConfig, slot_type: str) -> str:
    rendered = V2HighRiskPromptRenderer().render(
        prompt_id="v2.specialist.materializer.v1",
        context={
            "specialist": config.specialist,
            "slot_type": slot_type,
        },
        identity={
            "slot_type": slot_type,
            "specialist": config.specialist,
            "path_kind": "normal",
        },
    )
    return (
        f"{rendered.prompt_text}\n\n"
        f"{config.system_prompt}\n\n"
        f"Return only the JSON object required by the backend-owned prompt contract "
        f"for slot_type={slot_type}. Do not include markdown."
    )


def _allowed_reference_ids(request: V2SpecialistPromptRequest) -> set[str]:
    return {
        str(summary.get("asset_id"))
        for summary in [
            *request.reference_asset_summaries,
            *request.dependency_asset_summaries,
        ]
        if isinstance(summary, dict) and summary.get("asset_id")
    }


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
        "structured_output_schema_invalid": "specialist_output_schema_invalid",
        "structured_output_quality_failed": "specialist_output_quality_failed",
    }.get(code, "specialist_llm_call_failed")
