from collections.abc import Callable
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from app.core.config import Settings, get_settings
from app.schemas.workflow_v2 import (
    V2GenerationPlan,
    V2ProviderResult,
    V2ProviderTask,
    WorkflowItemV2,
    WorkflowMediaTypeV2,
    WorkflowSlotV2,
    WorkflowV2,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_bgm_policy import (
    BGM_SOFT_SKIP_CODE,
)
from app.services.v2_data_boundary import V2DataBoundaryError
from app.services.v2_final_composition_renderer import V2FinalCompositionRenderer
from app.services.v2_generation_integrity import (
    V2GenerationIntegrityError,
    V2GenerationIntegrityService,
)
from app.services.v2_provider_prompt_compiler import (
    V2ProviderPromptCompiler,
    V2ProviderPromptCompilerError,
)
from app.services.v2_provider_input_quality import V2ProviderInputEngineeringService
from app.services.v2_provider_reference_input_delivery import (
    V2DeliveredReferenceSet,
    V2ProviderReferenceInputDeliveryService,
)
from app.services.v2_provider_references import (
    V2ReferenceAdaptation,
    adapt_provider_references,
)
from app.services.v2_reference_audit import V2ReferenceAuditBuilder, V2ReferenceAuditError
from app.services.v2_reference_delivery import attach_reference_delivery_audit
from app.services.v2_runtime_prompt_governance import (
    V2PromptGovernanceError,
    apply_compiled_prompt_to_payload,
    compile_v2_provider_prompt,
)
from app.tools.media_provider_factory import build_media_provider
from app.tools.media_provider_protocol import (
    SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS,
    MediaApiError,
    MediaConfigurationError,
    MediaProvider,
)
from app.tools.bgm_provider_factory import (
    bgm_provider_configuration_error,
    build_bgm_provider_adapter,
    is_supported_bgm_provider,
)
from app.tools.volcengine_image_generations import V2ProviderRequestContractError


ProviderFactory = Callable[[Settings], MediaProvider]

V2_IMAGE_SLOT_TYPES = {
    "product_main_image",
    "product_multi_view_grid",
    "character_main_image",
    "character_three_view",
    "scene_main_image",
    "scene_multi_view_grid",
    "free_output",
}

V2_PROMPT_SOURCE_CONTRACT = "v2_canonical_provider_prompt"
V2_LEGACY_PROMPT_FIELDS = {
    "location",
    "lighting",
    "atmosphere",
    "shot",
    "visual",
    "camera",
    "action",
    "appearance",
    "personality",
    "actual_provider_prompt",
    "actual_provider_request_prompt",
}
_MAX_PROVIDER_DIAGNOSTIC_LENGTH = 2_048
_URL_OR_DATA_URL_PATTERN = re.compile(r"(?i)\b(?:https?://|data:)[^\s\"'<>]+")
_SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)\b(?P<key>authorization|api[_-]?key|access[_-]?key|token|secret|signature)"
    r"\s*(?:=|:)\s*(?:bearer\s+)?[^\s,;\"'}\]]+"
)
_LONG_BASE64_PATTERN = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{32,}={0,2}(?![A-Za-z0-9+/=])")


def _failure_prompt_provenance(
    payload: dict[str, Any],
    *,
    error_code: str,
) -> dict[str, Any] | None:
    provenance = payload.get("prompt_provenance")
    if not isinstance(provenance, dict):
        return None
    sanitized = sanitize_context_for_llm_text(provenance)
    if not isinstance(sanitized, dict):
        return None
    return {
        **sanitized,
        "validation_status": "failed",
        "error_code": error_code,
    }


def _provider_submit_diagnostics(
    payload: dict[str, Any],
    error_metadata: dict[str, Any] | None,
) -> tuple[dict[str, Any], str | None]:
    metadata = error_metadata or {}
    request_payload = metadata.get("payload")
    request_payload = request_payload if isinstance(request_payload, dict) else {}
    request_sources = (request_payload, payload)
    prompt_values = _request_prompt_values(request_sources)
    content_types, reference_count = _request_content_summary(request_sources)
    request_summary: dict[str, Any] = {
        "content_types": content_types,
        "reference_count": reference_count,
    }
    for field, keys, expected_type in (
        ("model", ("model", "provider_model", "model_id"), str),
        ("duration", ("duration", "duration_seconds", "provider_duration_seconds"), int),
        ("resolution", ("resolution",), str),
        ("ratio", ("ratio", "aspect_ratio"), str),
        ("generate_audio", ("generate_audio",), bool),
    ):
        value = _first_summary_value(request_sources, keys)
        if isinstance(value, expected_type) and not (
            expected_type is int and isinstance(value, bool)
        ):
            sanitized = (
                _safe_diagnostic_scalar(value, prompt_values) if isinstance(value, str) else value
            )
            if sanitized is not None:
                request_summary[field] = sanitized
    diagnostics: dict[str, Any] = {
        "stage": "provider_submit",
        "request_summary": request_summary,
    }
    http_status = _first_summary_value((metadata,), ("http_status", "status"))
    if isinstance(http_status, int) and not isinstance(http_status, bool):
        diagnostics["http_status"] = http_status
    provider_error_code = _first_summary_value(
        (metadata,),
        ("provider_error_code", "error_code", "code"),
    )
    if isinstance(provider_error_code, str):
        sanitized = _safe_diagnostic_scalar(provider_error_code, prompt_values)
        if sanitized is not None:
            diagnostics["provider_error_code"] = sanitized
    provider_request_id = _first_summary_value(
        (metadata,),
        ("provider_request_id", "request_id", "requestId"),
    )
    if isinstance(provider_request_id, str):
        sanitized = _safe_diagnostic_scalar(provider_request_id, prompt_values)
        if sanitized is not None:
            diagnostics["provider_request_id"] = sanitized
    response = _first_summary_value((metadata,), ("response_body", "response_text", "response"))
    response_details = _provider_response_details(response, prompt_values)
    for key in ("provider_error_code", "provider_request_id"):
        if key not in diagnostics and response_details.get(key) is not None:
            diagnostics[key] = response_details[key]
    response_summary = response_details.get("provider_response_summary")
    if isinstance(response_summary, str):
        diagnostics["provider_response_summary"] = response_summary
    provider_message = response_details.get("provider_message")
    return diagnostics, provider_message if isinstance(provider_message, str) else None


def _first_summary_value(sources: tuple[dict[str, Any], ...], keys: tuple[str, ...]) -> Any:
    for source in sources:
        for key in keys:
            if key in source:
                return source[key]
    return None


def _request_prompt_values(sources: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    values: set[str] = set()

    def collect(value: Any, key: str | None = None) -> None:
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                collect(nested_value, str(nested_key))
        elif isinstance(value, list):
            for item in value:
                collect(item, key)
        elif isinstance(value, str) and key is not None and "prompt" in key.lower():
            normalized = value.strip()
            if normalized:
                values.add(normalized)

    for source in sources:
        collect(source)
    return tuple(sorted(values, key=len, reverse=True))


def _request_content_summary(sources: tuple[dict[str, Any], ...]) -> tuple[list[str], int]:
    explicit_count = _first_summary_value(sources, ("reference_count",))
    if isinstance(explicit_count, int) and not isinstance(explicit_count, bool):
        return [], max(explicit_count, 0)
    content: list[Any] = []
    for source in sources:
        for key in ("content", "input_assets", "references"):
            value = source.get(key)
            if isinstance(value, list):
                content = value
                break
        if content:
            break
    reference_types = {"image", "image_url", "video", "video_url"}
    content_types: list[str] = []
    counted_content = 0
    for entry in content:
        if not isinstance(entry, dict):
            continue
        content_type = _first_summary_value((entry,), ("type", "content_type", "media_type"))
        if not isinstance(content_type, str):
            continue
        sanitized = _safe_diagnostic_scalar(content_type, ())
        if sanitized is not None and sanitized not in content_types:
            content_types.append(sanitized)
        if content_type.lower() in reference_types:
            counted_content += 1
    if counted_content:
        return content_types, counted_content
    for source in sources:
        value = source.get("reference_asset_ids")
        if isinstance(value, list):
            return content_types, len(value)
    return content_types, 0


def _provider_response_details(
    value: Any,
    prompt_values: tuple[str, ...],
) -> dict[str, str]:
    parsed = _json_response_object(value)
    if parsed is not None:
        nested_error = parsed.get("error")
        nested_error = nested_error if isinstance(nested_error, dict) else {}
        provider_error_code = _safe_diagnostic_scalar(
            _first_summary_value((nested_error, parsed), ("code",)),
            prompt_values,
        )
        provider_message = _safe_diagnostic_scalar(
            _first_summary_value((nested_error, parsed), ("message",)),
            prompt_values,
        )
        provider_request_id = _safe_diagnostic_scalar(
            _first_summary_value(
                (nested_error, parsed),
                ("request_id", "requestId"),
            ),
            prompt_values,
        )
        details: dict[str, str] = {}
        if provider_error_code is not None:
            details["provider_error_code"] = provider_error_code
        if provider_request_id is not None:
            details["provider_request_id"] = provider_request_id
        if provider_message is not None:
            details["provider_message"] = provider_message
            details["provider_response_summary"] = provider_message
        return details
    if not isinstance(value, str):
        return {}
    summary = _redacted_diagnostic_text(value, prompt_values)
    if summary is None:
        return {}
    return {"provider_message": summary, "provider_response_summary": summary}


def _json_response_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _bounded_provider_error_message(
    value: str,
    prompt_values: tuple[str, ...],
) -> str:
    return _redacted_diagnostic_text(value, prompt_values) or "Provider generation failed."


def _safe_diagnostic_scalar(value: Any, prompt_values: tuple[str, ...]) -> str | None:
    if not isinstance(value, str):
        return None
    redacted = _redacted_diagnostic_text(value, prompt_values)
    if redacted is None or "[redacted]" in redacted:
        return None
    return redacted


def _redacted_diagnostic_text(value: str, prompt_values: tuple[str, ...]) -> str | None:
    normalized = value.strip()
    if not normalized:
        return None
    for prompt_value in prompt_values:
        normalized = normalized.replace(prompt_value, "[redacted]")
    normalized = _URL_OR_DATA_URL_PATTERN.sub("[redacted-url]", normalized)
    normalized = _SENSITIVE_VALUE_PATTERN.sub(
        lambda match: f"{match.group('key')}=[redacted]",
        normalized,
    )
    normalized = _LONG_BASE64_PATTERN.sub("[redacted-base64]", normalized)
    return normalized[:_MAX_PROVIDER_DIAGNOSTIC_LENGTH].strip() or None


class V2ProviderExecutor:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        data_dir: Path | None = None,
        provider_factory: ProviderFactory | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._data_dir = data_dir or self._settings.media_data_dir
        self._uses_default_provider_factory = provider_factory is None
        self._provider_factory = provider_factory or build_media_provider
        self._provider: MediaProvider | None = None
        self._asset_store = V2AssetStoreService(self._data_dir)
        self._reference_delivery = V2ProviderReferenceInputDeliveryService(
            self._data_dir,
            settings=self._settings,
        )
        self._reference_audit_builder = V2ReferenceAuditBuilder(self._data_dir)
        self._provider_prompt_compiler = V2ProviderPromptCompiler()
        self._generation_integrity = V2GenerationIntegrityService()
        self._provider_input_quality = V2ProviderInputEngineeringService(self._data_dir)
        self._final_composition_renderer = V2FinalCompositionRenderer(
            data_dir=self._data_dir,
            settings=self._settings,
            asset_store=self._asset_store,
        )

    def execute(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        plan: V2GenerationPlan,
    ) -> V2ProviderResult:
        payload = sanitize_context_for_llm_text(plan.provider_payload)
        mode = self._settings.media_mode.strip().lower()
        provider_id = _provider_id_for_slot(slot, mode)
        if not _has_compiled_prompt(payload):
            try:
                compiled_prompt = compile_v2_provider_prompt(
                    workflow,
                    item,
                    slot,
                    provider_payload=payload,
                )
            except V2PromptGovernanceError as exc:
                return _prompt_governance_failure_result(
                    slot=slot,
                    payload=payload,
                    provider=provider_id,
                    reference_asset_ids=list(plan.reference_asset_ids),
                    error=exc,
                )
            payload = apply_compiled_prompt_to_payload(payload, compiled_prompt)
        elif not str(payload.get("provider_prompt") or "").strip():
            return _prompt_governance_failure_result(
                slot=slot,
                payload=payload,
                provider=provider_id,
                reference_asset_ids=list(plan.reference_asset_ids),
                error=V2PromptGovernanceError(
                    "v2_provider_prompt_empty",
                    "V2 provider prompt is empty after compilation.",
                    metadata={
                        "node_id": slot.node_id,
                        "item_id": item.item_id,
                        "slot_id": slot.slot_id,
                        "slot_type": slot.slot_type,
                        "media_type": slot.media_type,
                    },
                ),
            )
        adaptation = adapt_provider_references(
            data_dir=self._data_dir,
            slot=slot,
            provider=provider_id,
            media_type=slot.media_type,
            provider_payload=payload,
            reference_asset_ids=plan.reference_asset_ids,
        )
        payload = _payload_with_canonical_fields(adaptation.provider_payload)
        prompt_source_failure = self._apply_v2_prompt_source_audit(
            workflow=workflow,
            item=item,
            slot=slot,
            payload=payload,
            provider=provider_id,
            reference_asset_ids=list(adaptation.submitted_reference_asset_ids),
        )
        payload = prompt_source_failure[0]
        if prompt_source_failure[1] is not None:
            return prompt_source_failure[1]
        isolation_failure = self._provider_prompt_isolation_failure(
            slot=slot,
            payload=payload,
            provider=provider_id,
            reference_asset_ids=list(adaptation.submitted_reference_asset_ids),
        )
        if isolation_failure is not None:
            return isolation_failure
        payload, integrity_failure = self._generation_integrity_failure(
            workflow=workflow,
            item=item,
            slot=slot,
            payload=payload,
            provider=provider_id,
            reference_asset_ids=list(adaptation.submitted_reference_asset_ids),
        )
        if integrity_failure is not None:
            return integrity_failure
        payload, adaptation = self._apply_provider_input_quality(
            workflow=workflow,
            item=item,
            slot=slot,
            payload=payload,
            adaptation=adaptation,
        )
        payload = attach_reference_delivery_audit(payload, adaptation)
        shot_video_reference_failure = self._shot_video_reference_failure(
            item=item,
            slot=slot,
            payload=payload,
            adaptation=adaptation,
            provider=provider_id,
        )
        if shot_video_reference_failure is not None:
            return shot_video_reference_failure
        required_reference_failure = self._required_reference_drop_result(
            slot=slot,
            payload=payload,
            adaptation=adaptation,
            provider=provider_id,
        )
        if required_reference_failure is not None:
            return required_reference_failure
        try:
            payload = self._apply_and_validate_reference_audit(payload, adaptation)
            payload = self._provider_prompt_compiler.validate_provider_payload(payload)
        except V2ReferenceAuditError as exc:
            payload = exc.payload or payload
            return V2ProviderResult(
                status="failed",
                media_type=slot.media_type,
                provider=provider_id,
                provider_payload_snapshot=payload,
                reference_asset_ids=list(adaptation.submitted_reference_asset_ids),
                error_code=exc.code,
                error_message=str(exc),
                metadata={
                    **adaptation.metadata,
                    **(
                        {"reference_audit": payload["reference_audit"]}
                        if isinstance(payload.get("reference_audit"), dict)
                        else {}
                    ),
                },
            )
        except V2ProviderPromptCompilerError as exc:
            return self._provider_prompt_isolation_result(
                slot=slot,
                payload=exc.payload or payload,
                provider=provider_id,
                reference_asset_ids=list(adaptation.submitted_reference_asset_ids),
                error=exc,
            )
        plan = plan.model_copy(
            update={
                "provider_payload": payload,
                "reference_asset_ids": list(adaptation.submitted_reference_asset_ids),
                "reference_audit": dict(payload.get("reference_audit") or {}),
            }
        )
        if slot.slot_type == "final_video":
            return self._with_reference_adaptation(
                self._final_composition_renderer.render(workflow, item, slot, payload),
                adaptation,
            )

        if mode == "mock":
            return self._with_reference_adaptation(
                self._placeholder_result(
                    media_type=slot.media_type,
                    slot_type=slot.slot_type,
                    provider=f"dev_placeholder_{slot.media_type}",
                    provider_payload=payload,
                    reference_asset_ids=plan.reference_asset_ids,
                    metadata=adaptation.metadata,
                ),
                adaptation,
            )
        if mode != "real":
            return self._with_reference_adaptation(
                V2ProviderResult(
                    status="failed",
                    media_type=slot.media_type,
                    provider=slot.provider,
                    provider_payload_snapshot=payload,
                    reference_asset_ids=list(plan.reference_asset_ids),
                    error_code="provider_configuration_missing",
                    error_message=f"MEDIA_MODE must be 'mock' or 'real', got {self._settings.media_mode!r}.",
                    metadata=adaptation.metadata,
                ),
                adaptation,
            )

        missing_message = self._missing_real_config(slot.media_type)
        if missing_message:
            if slot.slot_type == "bgm_audio":
                return self._with_reference_adaptation(
                    V2ProviderResult(
                        status="skipped",
                        media_type=slot.media_type,
                        provider=provider_id,
                        provider_payload_snapshot=payload,
                        reference_asset_ids=list(plan.reference_asset_ids),
                        error_code=BGM_SOFT_SKIP_CODE,
                        error_message=missing_message,
                        metadata={
                            **adaptation.metadata,
                            "optional_dependency": True,
                            "soft_skip": True,
                            "stage": "provider_configuration",
                            "missing_configuration": True,
                        },
                    ),
                    adaptation,
                )
            if self._settings.v2_provider_allow_fallback:
                return self._with_reference_adaptation(
                    self._placeholder_result(
                        media_type=slot.media_type,
                        slot_type=slot.slot_type,
                        provider=f"dev_placeholder_{slot.media_type}",
                        provider_payload=payload,
                        reference_asset_ids=plan.reference_asset_ids,
                        metadata={
                            **adaptation.metadata,
                            "warnings": [
                                {
                                    "code": "provider_configuration_missing",
                                    "message": missing_message,
                                }
                            ],
                        },
                    ),
                    adaptation,
                )
            return self._with_reference_adaptation(
                V2ProviderResult(
                    status="failed",
                    media_type=slot.media_type,
                    provider=slot.provider,
                    provider_payload_snapshot=payload,
                    reference_asset_ids=list(plan.reference_asset_ids),
                    error_code="provider_configuration_missing",
                    error_message=missing_message,
                    metadata=adaptation.metadata,
                ),
                adaptation,
            )

        try:
            if slot.media_type == "image":
                return self._with_reference_adaptation(
                    self._execute_real_image(workflow, item, slot, payload, plan),
                    adaptation,
                )
            if slot.media_type == "audio":
                return self._with_reference_adaptation(
                    self._execute_real_audio(workflow, item, slot, payload, plan),
                    adaptation,
                )
            if slot.media_type == "video":
                return self._with_reference_adaptation(
                    self._execute_real_video(workflow, item, slot, payload, plan),
                    adaptation,
                )
        except V2DataBoundaryError:
            raise
        except V2ProviderRequestContractError as exc:
            return self._with_reference_adaptation(
                V2ProviderResult(
                    status="failed",
                    media_type=slot.media_type,
                    provider=provider_id,
                    provider_payload_snapshot=payload,
                    reference_asset_ids=list(adaptation.submitted_reference_asset_ids),
                    error_code=exc.code,
                    error_message=str(exc),
                    metadata={
                        "stage": exc.stage,
                        "reference_wire_audit": exc.audit.model_dump(mode="json"),
                    },
                ),
                adaptation,
            )
        except MediaConfigurationError as exc:
            return self._with_reference_adaptation(
                V2ProviderResult(
                    status="failed",
                    media_type=slot.media_type,
                    provider=slot.provider,
                    provider_payload_snapshot=payload,
                    reference_asset_ids=list(plan.reference_asset_ids),
                    error_code="provider_configuration_missing",
                    error_message=str(exc),
                    metadata=adaptation.metadata,
                ),
                adaptation,
            )
        except MediaApiError as exc:
            diagnostics, provider_message = _provider_submit_diagnostics(payload, exc.metadata)
            return self._with_reference_adaptation(
                V2ProviderResult(
                    status="failed",
                    media_type=slot.media_type,
                    provider=provider_id,
                    provider_payload_snapshot={"request_summary": diagnostics["request_summary"]},
                    reference_asset_ids=list(adaptation.submitted_reference_asset_ids),
                    error_code="provider_request_failed",
                    error_message=provider_message or "Provider request failed.",
                    metadata=diagnostics,
                ),
                adaptation,
            )
        except Exception as exc:  # noqa: BLE001 - provider failures become result state.
            diagnostics, _ = _provider_submit_diagnostics(payload, None)
            return self._with_reference_adaptation(
                V2ProviderResult(
                    status="failed",
                    media_type=slot.media_type,
                    provider=provider_id,
                    provider_payload_snapshot={"request_summary": diagnostics["request_summary"]},
                    reference_asset_ids=list(adaptation.submitted_reference_asset_ids),
                    error_code="provider_generation_failed",
                    error_message=_bounded_provider_error_message(
                        str(exc),
                        _request_prompt_values((payload,)),
                    ),
                    metadata=diagnostics,
                ),
                adaptation,
            )

        return self._with_reference_adaptation(
            V2ProviderResult(
                status="failed",
                media_type=slot.media_type,
                provider=slot.provider,
                provider_payload_snapshot=payload,
                reference_asset_ids=list(plan.reference_asset_ids),
                error_code="provider_generation_failed",
                error_message=f"Unsupported V2 provider media type: {slot.media_type}.",
                metadata=adaptation.metadata,
            ),
            adaptation,
        )

    def execute_minimal(
        self,
        *,
        workflow_id: str,
        slot_type: str,
        media_type: WorkflowMediaTypeV2,
        provider_payload: dict[str, Any],
    ) -> V2ProviderResult:
        missing_message = (
            self._missing_real_config(media_type)
            if self._settings.media_mode.strip().lower() == "real"
            else None
        )
        if missing_message and not self._settings.v2_provider_allow_fallback:
            return V2ProviderResult(
                status="failed",
                media_type=media_type,
                provider_payload_snapshot=sanitize_context_for_llm_text(provider_payload),
                error_code="provider_configuration_missing",
                error_message=missing_message,
            )
        return self._placeholder_result(
            media_type=media_type,
            slot_type=slot_type,
            provider=f"dev_placeholder_{media_type}",
            provider_payload={**provider_payload, "workflow_id": workflow_id},
            reference_asset_ids=[],
        )

    def poll_task(self, task: V2ProviderTask) -> V2ProviderResult:
        media_type = str(task.metadata.get("media_type") or "video")
        slot_type = str(task.metadata.get("slot_type") or "")
        if self._settings.media_mode.strip().lower() != "real":
            return V2ProviderResult(
                status="waiting",
                media_type=media_type,  # type: ignore[arg-type]
                remote_task_id=task.remote_task_id,
                provider=task.provider,
                provider_model=task.provider_model,
                provider_payload_snapshot=task.provider_payload_snapshot,
                metadata={"waiting_reason": "mock_provider_task_not_completed"},
            )
        try:
            if media_type == "audio" and slot_type == "bgm_audio" and task.remote_task_id:
                refreshed = self._retrieve_bgm_audio_task(task)
                return _result_from_provider_asset(
                    refreshed,
                    media_type="audio",
                    provider=task.provider,
                    provider_model=task.provider_model,
                    provider_payload=task.provider_payload_snapshot,
                    reference_asset_ids=list(task.metadata.get("reference_asset_ids") or []),
                )
            provider = self._media_provider()
            if (
                media_type == "video"
                and hasattr(provider, "retrieve_storyboard_video_task")
                and task.remote_task_id
            ):
                refreshed = provider.retrieve_storyboard_video_task(  # type: ignore[attr-defined]
                    task.remote_task_id,
                    workflow_id=task.workflow_id,
                    source_assets=list(task.metadata.get("reference_asset_ids") or []),
                    duration_seconds=int(task.metadata.get("duration_seconds") or 0),
                    segment_order=int(task.metadata.get("segment_order") or 1),
                    scene_id=str(task.metadata.get("scene_id") or task.item_id),
                    prompt=str(task.provider_payload_snapshot.get("provider_prompt") or ""),
                    resolution=str(task.metadata.get("resolution") or ""),
                    ratio=str(task.metadata.get("aspect_ratio") or ""),
                    download_media=True,
                    output_relative_path=(
                        Path("assets")
                        / "generated-provider"
                        / task.workflow_id
                        / "provider-task-results"
                        / task.task_id
                        / "output-0.mp4"
                    ),
                )
                return _result_from_provider_asset(
                    refreshed,
                    media_type="video",
                    provider=task.provider,
                    provider_model=task.provider_model,
                    provider_payload=task.provider_payload_snapshot,
                    reference_asset_ids=list(task.metadata.get("reference_asset_ids") or []),
                )
        except Exception as exc:  # noqa: BLE001 - task polling errors are persisted.
            error_code = (
                "bgm_provider_task_failed"
                if media_type == "audio" and slot_type == "bgm_audio"
                else "provider_generation_failed"
            )
            return V2ProviderResult(
                status="failed",
                media_type=media_type,  # type: ignore[arg-type]
                remote_task_id=task.remote_task_id,
                provider=task.provider,
                provider_model=task.provider_model,
                provider_payload_snapshot=task.provider_payload_snapshot,
                error_code=error_code,
                error_message=str(exc),
            )
        return V2ProviderResult(
            status="waiting",
            media_type=media_type,  # type: ignore[arg-type]
            remote_task_id=task.remote_task_id,
            provider=task.provider,
            provider_model=task.provider_model,
            provider_payload_snapshot=task.provider_payload_snapshot,
            metadata={"waiting_reason": "provider_task_still_running"},
        )

    def _provider_prompt_isolation_failure(
        self,
        *,
        slot: WorkflowSlotV2,
        payload: dict[str, Any],
        provider: str,
        reference_asset_ids: list[str],
    ) -> V2ProviderResult | None:
        try:
            self._provider_prompt_compiler.validate_provider_payload(payload)
        except V2ProviderPromptCompilerError as exc:
            return self._provider_prompt_isolation_result(
                slot=slot,
                payload=exc.payload or payload,
                provider=provider,
                reference_asset_ids=reference_asset_ids,
                error=exc,
            )
        return None

    def _apply_v2_prompt_source_audit(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        payload: dict[str, Any],
        provider: str,
        reference_asset_ids: list[str],
    ) -> tuple[dict[str, Any], V2ProviderResult | None]:
        canonical_prompt = str(payload.get("provider_prompt") or "").strip()
        actual_prompt = _actual_provider_prompt(payload, canonical_prompt)
        audit = _prompt_audit(
            workflow=workflow,
            item=item,
            slot=slot,
            payload=payload,
            canonical_prompt=canonical_prompt,
            actual_prompt=actual_prompt,
        )
        payload = {**payload, "prompt_audit": audit}
        if slot.slot_type == "bgm_audio" and not canonical_prompt:
            error_code = "bgm_prompt_empty"
            metadata: dict[str, Any] = {
                "stage": "provider_payload",
                "node_id": slot.node_id,
                "item_id": item.item_id,
                "slot_id": slot.slot_id,
                "slot_type": slot.slot_type,
                "prompt_audit": audit,
            }
            if provenance := _failure_prompt_provenance(payload, error_code=error_code):
                metadata["prompt_provenance"] = provenance
            return payload, V2ProviderResult(
                status="failed",
                media_type=slot.media_type,
                provider=provider,
                provider_payload_snapshot=sanitize_context_for_llm_text(payload),
                reference_asset_ids=list(reference_asset_ids),
                error_code=error_code,
                error_message="V2 BGM generation requires a non-empty provider prompt.",
                metadata=metadata,
            )
        if slot.media_type == "video" and not canonical_prompt:
            error_code = "v2_video_prompt_empty"
            metadata: dict[str, Any] = {
                "stage": "provider_payload",
                "node_id": slot.node_id,
                "item_id": item.item_id,
                "slot_id": slot.slot_id,
                "slot_type": slot.slot_type,
                "prompt_audit": audit,
            }
            if provenance := _failure_prompt_provenance(
                payload,
                error_code=error_code,
            ):
                metadata["prompt_provenance"] = provenance
            return payload, V2ProviderResult(
                status="failed",
                media_type=slot.media_type,
                provider=provider,
                provider_payload_snapshot=sanitize_context_for_llm_text(payload),
                reference_asset_ids=list(reference_asset_ids),
                error_code=error_code,
                error_message="V2 video generation requires a non-empty provider prompt.",
                metadata=metadata,
            )
        if audit["prompt_match"] is True:
            return payload, None
        error_code = (
            "v2_legacy_prompt_field_used"
            if audit["legacy_prompt_fields_used"]
            else "v2_provider_prompt_mismatch"
        )
        metadata: dict[str, Any] = {"prompt_audit": audit}
        if provenance := _failure_prompt_provenance(payload, error_code=error_code):
            metadata["prompt_provenance"] = provenance
        return payload, V2ProviderResult(
            status="failed",
            media_type=slot.media_type,
            provider=provider,
            provider_payload_snapshot=sanitize_context_for_llm_text(payload),
            reference_asset_ids=list(reference_asset_ids),
            error_code=error_code,
            error_message=(
                "V2 provider request prompt must exactly match canonical provider_prompt "
                "and must not use legacy prompt fields."
            ),
            metadata=metadata,
        )

    def _provider_prompt_isolation_result(
        self,
        *,
        slot: WorkflowSlotV2,
        payload: dict[str, Any],
        provider: str,
        reference_asset_ids: list[str],
        error: V2ProviderPromptCompilerError,
    ) -> V2ProviderResult:
        metadata: dict[str, Any] = {}
        if isinstance(error.audit, dict):
            metadata["prompt_isolation_audit"] = error.audit
        if provenance := _failure_prompt_provenance(payload, error_code=error.code):
            metadata["prompt_provenance"] = provenance
        return V2ProviderResult(
            status="failed",
            media_type=slot.media_type,
            provider=provider,
            provider_payload_snapshot=sanitize_context_for_llm_text(payload),
            reference_asset_ids=list(reference_asset_ids),
            error_code=error.code,
            error_message=str(error),
            metadata=sanitize_context_for_llm_text(metadata),
        )

    def _with_reference_adaptation(
        self,
        result: V2ProviderResult,
        adaptation: V2ReferenceAdaptation,
    ) -> V2ProviderResult:
        provider_payload = _payload_with_canonical_fields(
            result.provider_payload_snapshot or adaptation.provider_payload
        )
        provider_payload = self._with_result_reference_audit(
            provider_payload,
            result,
        )
        metadata = {
            **adaptation.metadata,
            **sanitize_context_for_llm_text(result.metadata),
        }
        if isinstance(provider_payload.get("generation_integrity"), dict):
            metadata["generation_integrity"] = provider_payload["generation_integrity"]
            metadata["integrity_audit"] = provider_payload["generation_integrity"]
        if isinstance(provider_payload.get("reference_audit"), dict):
            metadata["reference_audit"] = provider_payload["reference_audit"]
        if isinstance(provider_payload.get("reference_delivery_audit"), dict):
            metadata["reference_delivery_audit"] = provider_payload["reference_delivery_audit"]
        if isinstance(provider_payload.get("reference_wire_audit"), dict):
            metadata["reference_wire_audit"] = provider_payload["reference_wire_audit"]
        if isinstance(provider_payload.get("prompt_isolation_audit"), dict):
            metadata["prompt_isolation_audit"] = provider_payload["prompt_isolation_audit"]
        if isinstance(provider_payload.get("prompt_sanitization_audit"), dict):
            metadata["prompt_sanitization_audit"] = provider_payload["prompt_sanitization_audit"]
        if isinstance(provider_payload.get("fallback_field_completeness"), dict):
            metadata["fallback_field_completeness"] = provider_payload[
                "fallback_field_completeness"
            ]
        if isinstance(provider_payload.get("provider_prompt_contract"), dict):
            metadata["provider_prompt_contract"] = provider_payload["provider_prompt_contract"]
        if isinstance(provider_payload.get("prompt_registry_ref"), dict):
            metadata["prompt_registry_ref"] = provider_payload["prompt_registry_ref"]
        if isinstance(provider_payload.get("prompt_lineage"), dict):
            metadata["prompt_lineage"] = provider_payload["prompt_lineage"]
        if isinstance(provider_payload.get("prompt_content_profile"), dict):
            metadata["prompt_content_profile"] = provider_payload["prompt_content_profile"]
        if isinstance(provider_payload.get("provider_input_audit"), dict):
            metadata["provider_input_audit"] = provider_payload["provider_input_audit"]
        if isinstance(provider_payload.get("quality_flags"), list):
            metadata["quality_flags"] = list(provider_payload["quality_flags"])
        if isinstance(provider_payload.get("visual_style_contract"), dict):
            metadata["visual_style_contract"] = provider_payload["visual_style_contract"]
        if isinstance(provider_payload.get("visual_style_audit"), dict):
            metadata["visual_style_audit"] = provider_payload["visual_style_audit"]
        return result.model_copy(
            update={
                "provider_payload_snapshot": provider_payload,
                "reference_asset_ids": list(adaptation.submitted_reference_asset_ids),
                "metadata": metadata,
            }
        )

    def _generation_integrity_failure(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        payload: dict[str, Any],
        provider: str,
        reference_asset_ids: list[str],
    ) -> tuple[dict[str, Any], V2ProviderResult | None]:
        # The slot is authoritative when a direct caller supplies a compact
        # provider payload without canonical media fields.
        payload = {
            **payload,
            "media_type": slot.media_type,
            "slot_type": slot.slot_type,
        }
        prompt = str(payload.get("provider_prompt") or "")
        try:
            visual_style_audit = self._generation_integrity.validate_provider_style(payload)
            if visual_style_audit is not None:
                payload = {**payload, "visual_style_audit": visual_style_audit}
            audit = self._generation_integrity.validate_slot(
                workflow=workflow,
                item=item,
                slot=slot,
                provider_prompt=prompt,
                reference_asset_ids=reference_asset_ids,
            )
        except V2GenerationIntegrityError as exc:
            audit_payload = (
                exc.audit.model_dump(mode="json") if exc.audit is not None else exc.details
            )
            payload = {
                **payload,
                "generation_integrity": audit_payload,
                "integrity_audit": audit_payload,
            }
            metadata = sanitize_context_for_llm_text(
                {
                    "stage": exc.details.get("stage", "provider_prompt_compilation"),
                    "node_id": slot.node_id,
                    "item_id": item.item_id,
                    "slot_id": slot.slot_id,
                    "slot_type": slot.slot_type,
                    "generation_integrity": audit_payload,
                    "integrity_audit": audit_payload,
                    "visual_style_audit": exc.details.get("visual_style_audit"),
                }
            )
            return payload, V2ProviderResult(
                status="failed",
                media_type=slot.media_type,
                provider=provider,
                provider_payload_snapshot=sanitize_context_for_llm_text(payload),
                reference_asset_ids=list(reference_asset_ids),
                error_code=exc.code,
                error_message=str(exc),
                metadata=metadata,
            )
        audit_payload = audit.model_dump(mode="json")
        return {
            **payload,
            "generation_integrity": audit_payload,
            "integrity_audit": audit_payload,
        }, None

    def _apply_and_validate_reference_audit(
        self,
        payload: dict[str, Any],
        adaptation: V2ReferenceAdaptation,
    ) -> dict[str, Any]:
        audit = self._reference_audit_builder.audit_from_payload(payload)
        if audit is None:
            return payload
        audit = self._reference_audit_builder.apply_provider_adaptation(audit, adaptation)
        payload = {
            **payload,
            "reference_audit": self._reference_audit_builder.sanitize_reference_audit(audit),
        }
        try:
            self._reference_audit_builder.validate_provider_payload_matches_audit(
                audit,
                payload,
            )
        except V2ReferenceAuditError as exc:
            exc.payload = payload
            raise
        return payload

    def _apply_provider_input_quality(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        payload: dict[str, Any],
        adaptation: V2ReferenceAdaptation,
    ) -> tuple[dict[str, Any], V2ReferenceAdaptation]:
        updated, _audit, _flags = self._provider_input_quality.apply(
            workflow=workflow,
            item=item,
            slot=slot,
            provider_payload=payload,
            reference_asset_ids=list(adaptation.submitted_reference_asset_ids),
        )
        submitted = [
            str(asset_id) for asset_id in updated.get("reference_asset_ids", []) if str(asset_id)
        ]
        previous_submitted = set(adaptation.submitted_reference_asset_ids)
        role_dropped = [
            asset_id
            for asset_id in adaptation.submitted_reference_asset_ids
            if asset_id not in submitted
        ]
        warnings = [
            *adaptation.reference_usage_warnings,
            *[
                {
                    "code": "provider_reference_role_dropped",
                    "asset_id": asset_id,
                    "reason": "reference role is not allowed for this slot blueprint",
                }
                for asset_id in role_dropped
            ],
        ]
        requested = list(adaptation.requested_reference_asset_ids)
        dropped = _ordered_unique([*adaptation.dropped_reference_asset_ids, *role_dropped])
        if previous_submitted != set(submitted):
            updated = {
                **updated,
                "requested_reference_asset_ids": requested,
                "submitted_reference_asset_ids": submitted,
                "dropped_reference_asset_ids": dropped,
                "reference_usage_warnings": warnings,
            }
        return updated, replace(
            adaptation,
            provider_payload=updated,
            submitted_reference_asset_ids=submitted,
            dropped_reference_asset_ids=dropped,
            reference_usage_warnings=sanitize_context_for_llm_text(warnings),
        )

    def _with_result_reference_audit(
        self,
        payload: dict[str, Any],
        result: V2ProviderResult,
    ) -> dict[str, Any]:
        audit = self._reference_audit_builder.audit_from_payload(payload)
        if audit is None:
            return payload
        audit = audit.model_copy(
            update={
                "provider": result.provider or audit.provider,
                "provider_model": result.provider_model or audit.provider_model,
            },
            deep=True,
        )
        return {
            **payload,
            "reference_audit": self._reference_audit_builder.sanitize_reference_audit(audit),
        }

    def _required_reference_drop_result(
        self,
        *,
        slot: WorkflowSlotV2,
        payload: dict[str, Any],
        adaptation: V2ReferenceAdaptation,
        provider: str,
    ) -> V2ProviderResult | None:
        audit = payload.get("reference_audit")
        required_ids: list[str] = []
        if isinstance(audit, dict):
            required_ids.extend(
                str(asset_id) for asset_id in audit.get("required_reference_asset_ids") or []
            )
            required_ids.extend(
                str(asset_id) for asset_id in audit.get("dependency_reference_asset_ids") or []
            )
        required_ids = _ordered_unique(required_ids)
        dropped = set(adaptation.dropped_reference_asset_ids)
        missing_required = [asset_id for asset_id in required_ids if asset_id in dropped]
        if not missing_required:
            return None
        metadata = {
            **adaptation.metadata,
            "required_reference_asset_ids": required_ids,
            "missing_required_reference_asset_ids": missing_required,
        }
        if isinstance(audit, dict):
            metadata["reference_audit"] = audit
        return V2ProviderResult(
            status="failed",
            media_type=slot.media_type,
            provider=provider,
            provider_payload_snapshot=payload,
            reference_asset_ids=list(adaptation.submitted_reference_asset_ids),
            error_code="v2_required_reference_dropped",
            error_message=(
                "V2 required dependency references were not submitted to the provider: "
                + ", ".join(missing_required)
            ),
            metadata=sanitize_context_for_llm_text(metadata),
        )

    def _execute_real_image(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        payload: dict[str, Any],
        plan: V2GenerationPlan,
    ) -> V2ProviderResult:
        provider = self._media_provider()
        if not _is_supported_v2_image_slot(slot.slot_type):
            return V2ProviderResult(
                status="failed",
                media_type="image",
                provider=slot.provider,
                provider_payload_snapshot=payload,
                reference_asset_ids=list(plan.reference_asset_ids),
                error_code="unsupported_v2_image_slot",
                error_message=f"V2 canonical image adapter does not support slot_type={slot.slot_type}.",
            )
        if not hasattr(provider, "generate_v2_canonical_image"):
            return V2ProviderResult(
                status="failed",
                media_type="image",
                provider=slot.provider,
                provider_payload_snapshot=payload,
                reference_asset_ids=list(plan.reference_asset_ids),
                error_code="unsupported_v2_image_adapter",
                error_message="Real media provider does not implement generate_v2_canonical_image.",
            )
        delivery = self._deliver_references_for_provider(
            workflow=workflow,
            item=item,
            slot=slot,
            payload=payload,
            provider=_provider_id_for_slot(slot, self._settings.media_mode.strip().lower()),
            reference_asset_ids=plan.reference_asset_ids,
        )
        if isinstance(delivery, V2ProviderResult):
            return delivery
        payload = {**payload, "reference_input_delivery": delivery.audit}
        request_or_failure = self._v2_canonical_image_request(
            workflow=workflow,
            item=item,
            slot=slot,
            payload=payload,
            reference_asset_ids=delivery.delivered_reference_asset_ids,
            reference_assets=delivery.provider_assets(),
        )
        if isinstance(request_or_failure, V2ProviderResult):
            return request_or_failure
        request = request_or_failure
        output = provider.generate_v2_canonical_image(  # type: ignore[attr-defined]
            request,
            workflow.workflow_id,
        )
        payload = {
            **payload,
            "prompt_audit": request["prompt_audit"],
            **_provider_output_reference_wire_audit(output),
        }
        return _result_from_provider_output(
            output,
            media_type="image",
            provider_payload=payload,
            reference_asset_ids=delivery.delivered_reference_asset_ids,
        )

    def _v2_canonical_image_request(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        payload: dict[str, Any],
        reference_asset_ids: list[str],
        reference_assets: list[dict[str, Any]],
    ) -> dict[str, Any] | V2ProviderResult:
        canonical_prompt = str(payload.get("provider_prompt") or "").strip()
        actual_prompt = canonical_prompt
        audit = (
            payload.get("prompt_audit")
            if isinstance(payload.get("prompt_audit"), dict)
            else _prompt_audit(
                workflow=workflow,
                item=item,
                slot=slot,
                payload=payload,
                canonical_prompt=canonical_prompt,
                actual_prompt=actual_prompt,
            )
        )
        if not isinstance(audit, dict):
            audit = _prompt_audit(
                workflow=workflow,
                item=item,
                slot=slot,
                payload=payload,
                canonical_prompt=canonical_prompt,
                actual_prompt=actual_prompt,
            )
        if not canonical_prompt or not actual_prompt or not audit["prompt_match"]:
            return V2ProviderResult(
                status="failed",
                media_type="image",
                provider=slot.provider,
                provider_payload_snapshot={**payload, "prompt_audit": audit},
                reference_asset_ids=list(reference_asset_ids),
                error_code="v2_provider_prompt_mismatch",
                error_message="V2 provider request prompt must exactly match canonical provider_prompt.",
                metadata={"prompt_audit": audit},
            )
        return {
            "workflow_id": workflow.workflow_id,
            "node_id": slot.node_id,
            "item_id": item.item_id,
            "slot_id": slot.slot_id,
            "slot_type": slot.slot_type,
            "media_type": slot.media_type,
            "semantic_type": _semantic_type_for_slot(slot.slot_type, slot.media_type),
            "provider": _provider_label_for_v2_image_slot(slot),
            "prompt": actual_prompt,
            "negative_prompt": payload.get("negative_prompt"),
            "negative_constraints": payload.get("negative_constraints"),
            "reference_asset_ids": list(reference_asset_ids),
            "submitted_reference_asset_ids": list(reference_asset_ids),
            "reference_assets": reference_assets,
            "provider_params": dict(payload.get("provider_params") or {}),
            "prompt_contract_name": payload.get("prompt_contract_name"),
            "prompt_contract_version": payload.get("prompt_contract_version"),
            "prompt_audit": audit,
        }

    def _execute_real_audio(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        payload: dict[str, Any],
        plan: V2GenerationPlan,
    ) -> V2ProviderResult:
        prompt = str(payload.get("provider_prompt") or "").strip()
        audit = (
            payload.get("prompt_audit")
            if isinstance(payload.get("prompt_audit"), dict)
            else _prompt_audit(
                workflow=workflow,
                item=item,
                slot=slot,
                payload=payload,
                canonical_prompt=str(payload.get("provider_prompt") or "").strip(),
                actual_prompt=prompt,
            )
        )
        if not isinstance(audit, dict):
            audit = _prompt_audit(
                workflow=workflow,
                item=item,
                slot=slot,
                payload=payload,
                canonical_prompt=str(payload.get("provider_prompt") or "").strip(),
                actual_prompt=prompt,
            )
        payload = {**payload, "prompt_audit": audit}
        if not audit["canonical_provider_prompt"] or not audit["prompt_match"]:
            return V2ProviderResult(
                status="failed",
                media_type="audio",
                provider=slot.provider,
                provider_payload_snapshot=payload,
                reference_asset_ids=list(plan.reference_asset_ids),
                error_code="v2_provider_prompt_mismatch",
                error_message="V2 audio request prompt must exactly match canonical provider_prompt.",
                metadata={"prompt_audit": audit},
            )
        if slot.slot_type != "bgm_audio":
            return V2ProviderResult(
                status="failed",
                media_type="audio",
                provider=slot.provider,
                provider_payload_snapshot=payload,
                reference_asset_ids=list(plan.reference_asset_ids),
                error_code="unsupported_v2_audio_slot",
                error_message=f"V2 real audio only supports bgm_audio, got {slot.slot_type}.",
            )
        bgm_plan = _bgm_plan_from_payload(
            payload=payload,
            prompt=str(prompt or ""),
            duration_seconds=item.duration_seconds or workflow.duration_seconds,
            audio_mode=workflow.audio_mode,
            model=self._settings.bgm_model,
        )
        output = self._generate_bgm_audio(bgm_plan, workflow.workflow_id)
        return _result_from_provider_output(
            output,
            media_type="audio",
            provider_payload=payload,
            reference_asset_ids=plan.reference_asset_ids,
        )

    def _execute_real_video(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        payload: dict[str, Any],
        plan: V2GenerationPlan,
    ) -> V2ProviderResult:
        prompt = str(payload.get("provider_prompt") or "").strip()
        audit = (
            payload.get("prompt_audit")
            if isinstance(payload.get("prompt_audit"), dict)
            else _prompt_audit(
                workflow=workflow,
                item=item,
                slot=slot,
                payload=payload,
                canonical_prompt=prompt,
                actual_prompt=prompt,
            )
        )
        if not isinstance(audit, dict):
            audit = _prompt_audit(
                workflow=workflow,
                item=item,
                slot=slot,
                payload=payload,
                canonical_prompt=prompt,
                actual_prompt=prompt,
            )
        payload = {**payload, "prompt_audit": audit}
        if not prompt or not audit["prompt_match"]:
            if not prompt:
                return V2ProviderResult(
                    status="failed",
                    media_type="video",
                    provider=slot.provider,
                    provider_payload_snapshot=payload,
                    reference_asset_ids=list(plan.reference_asset_ids),
                    error_code="v2_video_prompt_empty",
                    error_message="V2 video generation requires a non-empty provider prompt.",
                    metadata={
                        "stage": "provider_payload",
                        "node_id": slot.node_id,
                        "item_id": item.item_id,
                        "slot_id": slot.slot_id,
                        "slot_type": slot.slot_type,
                        "prompt_audit": audit,
                    },
                )
            return V2ProviderResult(
                status="failed",
                media_type="video",
                provider=slot.provider,
                provider_payload_snapshot=payload,
                reference_asset_ids=list(plan.reference_asset_ids),
                error_code="v2_provider_prompt_mismatch",
                error_message="V2 video request prompt must exactly match canonical provider_prompt.",
                metadata={"prompt_audit": audit},
            )
        duration_seconds = int(
            payload.get("provider_duration_seconds")
            or slot.provider_params.get("duration_seconds")
            or item.metadata.get("provider_duration_seconds")
            or item.duration_seconds
            or workflow.duration_seconds
        )
        if duration_seconds not in SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS:
            return V2ProviderResult(
                status="failed",
                media_type="video",
                provider=_provider_id_for_slot(slot, self._settings.media_mode.strip().lower()),
                provider_payload_snapshot=payload,
                reference_asset_ids=list(plan.reference_asset_ids),
                error_code="v2_video_duration_unsupported",
                error_message=(
                    "V2 storyboard video duration must be one of "
                    f"{sorted(SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS)} seconds, "
                    f"got {duration_seconds}."
                ),
                metadata={
                    "stage": "provider_payload",
                    "node_id": slot.node_id,
                    "item_id": item.item_id,
                    "slot_id": slot.slot_id,
                    "slot_type": slot.slot_type,
                    "requested_duration_seconds": duration_seconds,
                    "supported_duration_seconds": sorted(SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS),
                    "prompt_audit": audit,
                },
            )
        delivery = self._deliver_references_for_provider(
            workflow=workflow,
            item=item,
            slot=slot,
            payload=payload,
            provider=_provider_id_for_slot(slot, self._settings.media_mode.strip().lower()),
            reference_asset_ids=plan.reference_asset_ids,
        )
        if isinstance(delivery, V2ProviderResult):
            return delivery
        output_resolution = _shot_video_output_resolution(
            workflow=workflow,
            slot=slot,
            settings=self._settings,
        )
        payload = {
            **payload,
            "provider_params": {
                **dict(payload.get("provider_params") or {}),
                "output_resolution": output_resolution,
            },
            "reference_input_delivery": delivery.audit,
        }
        provider = self._media_provider()
        output = provider.generate_storyboard_video(
            {
                "segments": [
                    {
                        "scene_id": item.item_id,
                        "order": int(item.shot_index or 1),
                        "prompt": prompt,
                        "duration_seconds": duration_seconds,
                        "source_assets": delivery.delivered_reference_asset_ids,
                        "storyboard_content": payload.get("storyboard_content"),
                        "dialogue": payload.get("dialogue"),
                        "audio_description": payload.get("audio_description"),
                        "voice_style": payload.get("voice_style"),
                        "video_negative_constraints": payload.get("video_negative_constraints"),
                        "time_segments": payload.get("time_segments", []),
                        "shot_cell_asset_ids": payload.get("shot_cell_asset_ids", []),
                    }
                ],
                "input_assets": delivery.provider_assets(),
                "duration_seconds": duration_seconds,
                "aspect_ratio": workflow.aspect_ratio,
                "output_resolution": output_resolution,
            },
            workflow.workflow_id,
        )
        return _result_from_provider_output(
            output,
            media_type="video",
            provider_payload=payload,
            reference_asset_ids=delivery.delivered_reference_asset_ids,
        )

    def _deliver_references_for_provider(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        payload: dict[str, Any],
        provider: str,
        reference_asset_ids: list[str],
    ) -> V2DeliveredReferenceSet | V2ProviderResult:
        delivery = self._reference_delivery.resolve_reference_assets_for_provider(
            workflow_id=workflow.workflow_id,
            asset_ids=reference_asset_ids,
            provider=provider,
            target_media_type=slot.media_type,
            slot_id=slot.slot_id,
        )
        if not delivery.failures:
            return delivery
        metadata = {
            "stage": "provider_reference_delivery",
            "workflow_id": workflow.workflow_id,
            "node_id": slot.node_id,
            "item_id": item.item_id,
            "slot_id": slot.slot_id,
            "slot_type": slot.slot_type,
            "reference_input_delivery": delivery.audit,
            "delivery_failures": [failure.model_dump(mode="json") for failure in delivery.failures],
        }
        first_failure = delivery.failures[0]
        return V2ProviderResult(
            status="failed",
            media_type=slot.media_type,
            provider=provider,
            provider_payload_snapshot=sanitize_context_for_llm_text(
                {**payload, "reference_input_delivery": delivery.audit}
            ),
            reference_asset_ids=delivery.delivered_reference_asset_ids,
            error_code=first_failure.code,
            error_message=first_failure.message,
            metadata=sanitize_context_for_llm_text(metadata),
        )

    def _media_provider(self) -> MediaProvider:
        if self._provider is None:
            self._provider = self._provider_factory(self._settings)
        return self._provider

    def _generate_bgm_audio(
        self,
        bgm_plan: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        if self._uses_default_provider_factory:
            adapter = build_bgm_provider_adapter(self._settings, self._data_dir)
            asset = adapter.generate_bgm_audio(bgm_plan, workflow_id)
            return {
                "provider": asset.get("provider") or self._settings.bgm_provider,
                "model": asset.get("model") or self._settings.bgm_model,
                "asset_id": "bgm-audio",
                "assets": [asset],
                "output_assets": [asset],
                "status": asset.get("status", "submitted"),
            }
        provider = self._media_provider()
        if not hasattr(provider, "generate_bgm_audio"):
            raise MediaConfigurationError(
                "Real BGM provider does not implement generate_bgm_audio."
            )
        return provider.generate_bgm_audio(bgm_plan, workflow_id)  # type: ignore[attr-defined]

    def _retrieve_bgm_audio_task(self, task: V2ProviderTask) -> dict[str, Any]:
        if self._uses_default_provider_factory:
            adapter = build_bgm_provider_adapter(self._settings, self._data_dir)
            provider_payload = {
                **task.provider_payload_snapshot,
                **(
                    dict(task.metadata.get("provider_asset") or {})
                    if isinstance(task.metadata.get("provider_asset"), dict)
                    else {}
                ),
                "expired_remote_reconciliation": task.metadata.get("expired_remote_reconciliation"),
            }
            return adapter.retrieve_bgm_audio_task(
                task.remote_task_id or "",
                workflow_id=task.workflow_id,
                provider_payload=provider_payload,
                download_media=True,
            )
        provider = self._media_provider()
        if not hasattr(provider, "retrieve_bgm_audio_task"):
            return {
                "asset_id": task.asset_id,
                "task_id": task.remote_task_id,
                "status": "submitted",
            }
        return provider.retrieve_bgm_audio_task(  # type: ignore[attr-defined]
            task.remote_task_id or "",
            workflow_id=task.workflow_id,
            provider_payload=task.provider_payload_snapshot,
            download_media=True,
        )

    def _missing_real_config(self, media_type: str) -> str | None:
        if media_type == "image" and (
            not self._settings.image_generation_api_key
            or not self._settings.image_generation_endpoint
        ):
            return "Real image provider requires IMAGE_GENERATION_API_KEY and IMAGE_GENERATION_ENDPOINT."
        if media_type == "video" and (
            not self._settings.video_generation_api_key
            or not self._settings.video_generation_endpoint
        ):
            return "Real video provider requires VIDEO_GENERATION_API_KEY and VIDEO_GENERATION_ENDPOINT."
        if (
            media_type == "audio"
            and self._uses_default_provider_factory
            and is_supported_bgm_provider(self._settings)
        ):
            return bgm_provider_configuration_error(self._settings)
        return None

    def _placeholder_result(
        self,
        *,
        media_type: WorkflowMediaTypeV2,
        slot_type: str,
        provider: str,
        provider_payload: dict[str, Any],
        reference_asset_ids: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> V2ProviderResult:
        prompt = str(provider_payload.get("provider_prompt") or "")
        audit = provider_payload.get("prompt_audit")
        if not isinstance(audit, dict):
            audit = _minimal_prompt_audit(
                slot_type=slot_type,
                canonical_prompt=prompt,
                actual_prompt=prompt,
                payload=provider_payload,
            )
        provider_payload = {**provider_payload, "prompt_audit": audit}
        metadata_payload = {**dict(metadata or {}), "prompt_audit": audit}
        if isinstance(provider_payload.get("provider_input_audit"), dict):
            metadata_payload["provider_input_audit"] = provider_payload["provider_input_audit"]
        if isinstance(provider_payload.get("provider_prompt_contract"), dict):
            metadata_payload["provider_prompt_contract"] = provider_payload[
                "provider_prompt_contract"
            ]
        if isinstance(provider_payload.get("prompt_sanitization_audit"), dict):
            metadata_payload["prompt_sanitization_audit"] = provider_payload[
                "prompt_sanitization_audit"
            ]
        if isinstance(provider_payload.get("fallback_field_completeness"), dict):
            metadata_payload["fallback_field_completeness"] = provider_payload[
                "fallback_field_completeness"
            ]
        if isinstance(provider_payload.get("reference_delivery_audit"), dict):
            metadata_payload["reference_delivery_audit"] = provider_payload[
                "reference_delivery_audit"
            ]
        if isinstance(provider_payload.get("quality_flags"), list):
            metadata_payload["quality_flags"] = list(provider_payload["quality_flags"])
        return V2ProviderResult(
            status="completed",
            media_type=media_type,
            asset_bytes=_placeholder_bytes(media_type, slot_type),
            provider=provider,
            provider_model="v2-dev-placeholder",
            provider_payload_snapshot=sanitize_context_for_llm_text(provider_payload),
            reference_asset_ids=list(reference_asset_ids),
            metadata=sanitize_context_for_llm_text(metadata_payload),
        )

    def _shot_video_reference_failure(
        self,
        *,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        payload: dict[str, Any],
        adaptation: V2ReferenceAdaptation,
        provider: str,
    ) -> V2ProviderResult | None:
        if slot.slot_type != "shot_video_segment":
            return None
        missing_cell_ids = _missing_required_shot_cell_ids(item, self._asset_store)
        if not missing_cell_ids:
            return None
        audit = payload.get("reference_delivery_audit")
        metadata = {
            **adaptation.metadata,
            "stage": "provider_reference_delivery",
            "node_id": slot.node_id,
            "item_id": item.item_id,
            "slot_id": slot.slot_id,
            "shot_id": item.shot_id or item.item_id,
            "missing_cell_ids": missing_cell_ids,
        }
        if isinstance(audit, dict):
            metadata["reference_delivery_audit"] = audit
        if isinstance(payload.get("provider_prompt_contract"), dict):
            metadata["provider_prompt_contract"] = payload["provider_prompt_contract"]
        return V2ProviderResult(
            status="failed",
            media_type=slot.media_type,
            provider=provider,
            provider_payload_snapshot=sanitize_context_for_llm_text(payload),
            reference_asset_ids=list(adaptation.submitted_reference_asset_ids),
            error_code="v2_provider_reference_file_missing",
            error_message=(
                "Storyboard video generation requires selected shot cell image references: "
                + ", ".join(missing_cell_ids)
            ),
            metadata=sanitize_context_for_llm_text(metadata),
        )


def _result_from_provider_output(
    output: dict[str, Any],
    *,
    media_type: WorkflowMediaTypeV2,
    provider_payload: dict[str, Any],
    reference_asset_ids: list[str],
) -> V2ProviderResult:
    assets = [asset for asset in output.get("assets", []) if isinstance(asset, dict)]
    segments = [segment for segment in output.get("segments", []) if isinstance(segment, dict)]
    selected = (assets or segments or [output])[0]
    return _result_from_provider_asset(
        selected,
        media_type=media_type,
        provider=output.get("provider") or selected.get("provider"),
        provider_model=output.get("model") or selected.get("model"),
        provider_payload=provider_payload,
        reference_asset_ids=reference_asset_ids,
    )


def _provider_output_reference_wire_audit(output: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidate = output.get("reference_wire_audit")
    if not isinstance(candidate, dict):
        assets = output.get("assets")
        if isinstance(assets, list) and assets and isinstance(assets[0], dict):
            candidate = assets[0].get("reference_wire_audit")
    if not isinstance(candidate, dict):
        return {}
    return {"reference_wire_audit": sanitize_context_for_llm_text(candidate)}


def _provider_id_for_slot(slot: WorkflowSlotV2, media_mode: str) -> str:
    if slot.slot_type == "final_video":
        return "local_composition_ffmpeg"
    if media_mode == "mock":
        return f"dev_placeholder_{slot.media_type}"
    return slot.provider or f"real_{slot.media_type}_provider"


def _shot_video_output_resolution(
    *,
    workflow: WorkflowV2,
    slot: WorkflowSlotV2,
    settings: Settings,
) -> str:
    return str(
        slot.provider_params.get("output_resolution")
        or slot.provider_params.get("resolution")
        or workflow.output_resolution
        or settings.video_generation_resolution
    )


def _payload_with_canonical_fields(payload: dict[str, Any]) -> dict[str, Any]:
    canonical = payload.get("canonical_provider_payload")
    if not isinstance(canonical, dict):
        return payload
    canonical_payload = dict(canonical)
    if isinstance(payload.get("reference_asset_ids"), list):
        canonical_payload["reference_asset_ids"] = list(payload["reference_asset_ids"])
    merged = {
        **payload,
        **{key: value for key, value in canonical_payload.items() if value is not None},
    }
    merged["canonical_provider_payload"] = canonical_payload
    return sanitize_context_for_llm_text(merged)


def _has_compiled_prompt(payload: dict[str, Any]) -> bool:
    return isinstance(payload.get("compiled_prompt"), dict) and isinstance(
        payload.get("prompt_provenance"),
        dict,
    )


def _prompt_governance_failure_result(
    *,
    slot: WorkflowSlotV2,
    payload: dict[str, Any],
    provider: str,
    reference_asset_ids: list[str],
    error: V2PromptGovernanceError,
) -> V2ProviderResult:
    return V2ProviderResult(
        status="failed",
        media_type=slot.media_type,
        provider=provider,
        provider_payload_snapshot=payload,
        reference_asset_ids=list(reference_asset_ids),
        error_code=error.code,
        error_message=str(error),
        metadata={
            "stage": "prompt_governance",
            **sanitize_context_for_llm_text(error.metadata),
        },
    )


def _prompt_audit(
    *,
    workflow: WorkflowV2,
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    payload: dict[str, Any],
    canonical_prompt: str,
    actual_prompt: str,
) -> dict[str, Any]:
    del workflow
    return _minimal_prompt_audit(
        slot_type=slot.slot_type,
        canonical_prompt=canonical_prompt,
        actual_prompt=actual_prompt,
        payload=payload,
        node_id=slot.node_id,
        item_id=item.item_id,
        slot_id=slot.slot_id,
        prompt_contract_name=payload.get("prompt_contract_name"),
        prompt_contract_version=payload.get("prompt_contract_version"),
    )


def _minimal_prompt_audit(
    *,
    slot_type: str,
    canonical_prompt: str,
    actual_prompt: str,
    payload: dict[str, Any],
    node_id: str | None = None,
    item_id: str | None = None,
    slot_id: str | None = None,
    prompt_contract_name: Any = None,
    prompt_contract_version: Any = None,
) -> dict[str, Any]:
    legacy_present = _legacy_prompt_fields_present(payload)
    prompt_match = (
        bool(canonical_prompt) and bool(actual_prompt) and actual_prompt == canonical_prompt
    )
    legacy_used = _legacy_prompt_fields_used(
        payload=payload,
        prompt_match=prompt_match,
    )
    return sanitize_context_for_llm_text(
        {
            "canonical_provider_prompt": canonical_prompt,
            "actual_provider_request_prompt": actual_prompt,
            "canonical_provider_prompt_hash": _prompt_hash(canonical_prompt),
            "actual_provider_prompt_hash": _prompt_hash(actual_prompt),
            "prompt_match": prompt_match,
            "prompt_source_contract": V2_PROMPT_SOURCE_CONTRACT,
            "legacy_prompt_fields_present": legacy_present,
            "legacy_prompt_fields_used": legacy_used,
            "conflicting_prompt_override_fields": _conflicting_prompt_override_fields(
                payload,
                canonical_prompt,
            ),
            "prompt_contract_name": prompt_contract_name,
            "prompt_contract_version": prompt_contract_version,
            "slot_type": slot_type,
            "node_id": node_id,
            "item_id": item_id,
            "slot_id": slot_id,
        }
    )


def _actual_provider_prompt(payload: dict[str, Any], canonical_prompt: str) -> str:
    for key in ("actual_provider_request_prompt", "actual_provider_prompt"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return canonical_prompt


def _prompt_hash(prompt: str) -> str:
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _legacy_prompt_fields_present(payload: Any) -> list[str]:
    fields: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            normalized_key = key_text.strip().lower()
            if normalized_key in V2_LEGACY_PROMPT_FIELDS:
                fields.append(key_text)
            if normalized_key == "prompt_audit":
                continue
            fields.extend(_legacy_prompt_fields_present(value))
    elif isinstance(payload, list):
        for value in payload:
            fields.extend(_legacy_prompt_fields_present(value))
    return _ordered_unique(fields)


def _legacy_prompt_fields_used(
    *,
    payload: dict[str, Any],
    prompt_match: bool,
) -> list[str]:
    if prompt_match:
        return []
    provenance = payload.get("prompt_provenance")
    if not isinstance(provenance, dict):
        return []
    used: list[str] = []
    compiler = provenance.get("compiler")
    if _is_explicit_legacy_prompt_provenance(compiler):
        used.append("prompt_provenance.compiler")
    source_fields = provenance.get("source_fields")
    if isinstance(source_fields, list) and any(
        _is_explicit_legacy_prompt_provenance(value) for value in source_fields
    ):
        used.append("prompt_provenance.source_fields")
    adapted_fields = provenance.get("legacy_fields_adapted")
    if isinstance(adapted_fields, list) and adapted_fields:
        used.append("prompt_provenance.legacy_fields_adapted")
    return used


def _conflicting_prompt_override_fields(
    payload: dict[str, Any],
    canonical_prompt: str,
) -> list[str]:
    return [
        key
        for key in ("actual_provider_request_prompt", "actual_provider_prompt")
        if isinstance(payload.get(key), str)
        and payload[key].strip()
        and payload[key].strip() != canonical_prompt
    ]


def _is_explicit_legacy_prompt_provenance(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized.startswith("v1_") or normalized.startswith("v1.") or "legacy" in normalized


def _is_supported_v2_image_slot(slot_type: str) -> bool:
    return slot_type in V2_IMAGE_SLOT_TYPES or slot_type.startswith("shot_cell_")


def _provider_label_for_v2_image_slot(slot: WorkflowSlotV2) -> str:
    if slot.provider:
        return slot.provider
    if slot.slot_type.startswith("shot_cell_"):
        return "volcengine-storyboard-image-generation"
    return {
        "product_main_image": "volcengine-product-image-generation",
        "product_multi_view_grid": "volcengine-product-image-generation",
        "character_main_image": "volcengine-character-image-generation",
        "character_three_view": "volcengine-character-turnaround-generation",
        "scene_main_image": "volcengine-scene-reference-generation",
        "scene_multi_view_grid": "volcengine-scene-multiview-generation",
        "free_output": "volcengine-free-image-generation",
    }.get(slot.slot_type, "volcengine-v2-canonical-image-generation")


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in (str(raw).strip() for raw in values) if value))


def _semantic_type_for_slot(slot_type: str, media_type: str | None = None) -> str:
    if slot_type.startswith("shot_cell_"):
        return "shot_cell_image"
    if slot_type == "free_output":
        return {
            "image": "free_image",
            "video": "free_video",
            "audio": "free_audio",
        }.get(media_type or "", "free_image")
    return {
        "product_main_image": "product_main_image",
        "product_multi_view_grid": "product_multi_view_grid",
        "character_main_image": "character_main_image",
        "character_three_view": "character_three_view",
        "scene_main_image": "scene_main_image",
        "scene_multi_view_grid": "scene_multi_view_grid",
        "bgm_audio": "bgm_audio",
        "shot_video_segment": "shot_video_segment",
        "final_video": "final_video",
    }.get(slot_type, slot_type)


def _missing_required_shot_cell_ids(
    item: WorkflowItemV2,
    asset_store: V2AssetStoreService,
) -> list[str]:
    missing: list[str] = []
    slots_by_type = {slot.slot_type: slot for slot in item.slots}
    for index in range(1, 5):
        cell_id = f"shot_cell_{index}"
        cell = slots_by_type.get(cell_id)
        if cell is None or not cell.selected_asset_id:
            missing.append(cell_id)
            continue
        if not asset_store.asset_exists(cell.selected_asset_id):
            missing.append(cell_id)
    return missing


def _bgm_plan_from_payload(
    *,
    payload: dict[str, Any],
    prompt: str,
    duration_seconds: int,
    audio_mode: str,
    model: str | None,
) -> dict[str, Any]:
    return {
        "prompt": _bgm_provider_prompt(
            prompt=prompt,
            duration_seconds=duration_seconds,
            payload=payload,
        ),
        "duration_seconds": duration_seconds,
        "audio_mode": audio_mode,
        "negative_constraints": payload.get("negative_constraints"),
        "ad_tone": payload.get("ad_tone"),
        "brand_emotion": payload.get("brand_emotion"),
        "pace": payload.get("pace"),
        "music_mood": payload.get("music_mood") or payload.get("mood"),
        "energy": payload.get("energy"),
        "instrumentation": payload.get("instrumentation"),
        "commercial_pacing": payload.get("commercial_pacing"),
        "audio_constraints": {"no_vocals": True, "no_lyrics": True},
        "loop_behavior": payload.get("loop_behavior"),
        "model": model,
    }


def _bgm_provider_prompt(
    *,
    prompt: str,
    duration_seconds: int,
    payload: dict[str, Any],
) -> str:
    mood = str(payload.get("music_mood") or payload.get("mood") or "brand-aligned").strip()
    pace = str(payload.get("pace") or "commercially paced").strip()
    energy = str(payload.get("energy") or "supportive advertising energy").strip()
    instrumentation = str(
        payload.get("instrumentation") or "instrumental background music bed"
    ).strip()
    commercial_pacing = str(
        payload.get("commercial_pacing") or "clear commercial pacing under visuals"
    ).strip()
    return (
        f"{prompt.strip()}\n"
        f"Mood: {mood}.\n"
        f"Pace: {pace}.\n"
        f"Energy: {energy}.\n"
        f"Duration: {duration_seconds} seconds.\n"
        f"Instrumentation: {instrumentation}.\n"
        f"Commercial pacing: {commercial_pacing}.\n"
        "No vocals. No lyrics. No narration. No spoken dialogue. No sound effects."
    ).strip()


def _result_from_provider_asset(
    asset: dict[str, Any],
    *,
    media_type: WorkflowMediaTypeV2,
    provider: str | None,
    provider_model: str | None,
    provider_payload: dict[str, Any],
    reference_asset_ids: list[str],
) -> V2ProviderResult:
    status = str(asset.get("status") or "").lower()
    task_id = asset.get("task_id") or asset.get("remote_task_id")
    local_path = asset.get("local_path") or asset.get("file_path")
    download_status = str(asset.get("download_status") or "").lower()
    metadata = _provider_asset_metadata(asset, provider_payload)
    if download_status == "failed":
        download_error_code = str(asset.get("download_error_code") or "provider_result_unavailable")
        return V2ProviderResult(
            status="failed",
            media_type=media_type,
            local_file_path=local_path if isinstance(local_path, str) else None,
            remote_task_id=task_id if isinstance(task_id, str) else None,
            provider=provider,
            provider_model=provider_model,
            provider_payload_snapshot=sanitize_context_for_llm_text(provider_payload),
            reference_asset_ids=list(reference_asset_ids),
            error_code=download_error_code,
            error_message=str(
                asset.get("error") or asset.get("download_error") or "Provider failed."
            ),
            metadata={
                **metadata,
                "stage": "provider_result_download",
                "download_attempted": True,
                "download_status": "failed",
                "download_retryable": bool(asset.get("download_retryable")),
                "download_error_code": download_error_code,
                "download_http_status": asset.get("download_http_status"),
                "download_expected_bytes": asset.get("download_expected_bytes"),
                "download_received_bytes": asset.get("download_received_bytes"),
                "remote_status": status or "succeeded",
            },
        )
    if status == "failed":
        return V2ProviderResult(
            status="failed",
            media_type=media_type,
            local_file_path=local_path if isinstance(local_path, str) else None,
            remote_task_id=task_id if isinstance(task_id, str) else None,
            provider=provider,
            provider_model=provider_model,
            provider_payload_snapshot=sanitize_context_for_llm_text(provider_payload),
            reference_asset_ids=list(reference_asset_ids),
            error_code=str(asset.get("error_code") or "provider_generation_failed"),
            error_message=str(asset.get("error") or "Provider failed."),
            metadata=metadata,
        )
    if task_id and not local_path:
        return V2ProviderResult(
            status="waiting",
            media_type=media_type,
            remote_task_id=str(task_id),
            provider=provider,
            provider_model=provider_model,
            provider_payload_snapshot=sanitize_context_for_llm_text(provider_payload),
            reference_asset_ids=list(reference_asset_ids),
            metadata={
                **metadata,
                "waiting_reason": "provider_task_submitted",
            },
        )

    if isinstance(local_path, str) and local_path.strip():
        download_metadata: dict[str, Any] = {}
        if media_type == "video" and download_status == "downloaded":
            download_metadata = {
                "stage": "provider_result_download",
                "download_attempted": True,
                "download_status": "downloaded",
                "remote_status": status or "succeeded",
            }
        return V2ProviderResult(
            status="completed",
            media_type=media_type,
            local_file_path=local_path.strip(),
            remote_task_id=str(task_id) if task_id else None,
            provider=provider,
            provider_model=provider_model,
            provider_payload_snapshot=sanitize_context_for_llm_text(provider_payload),
            reference_asset_ids=list(reference_asset_ids),
            metadata={**metadata, **download_metadata},
        )
    return V2ProviderResult(
        status="failed",
        media_type=media_type,
        remote_task_id=str(task_id) if task_id else None,
        provider=provider,
        provider_model=provider_model,
        provider_payload_snapshot=sanitize_context_for_llm_text(provider_payload),
        reference_asset_ids=list(reference_asset_ids),
        error_code="provider_output_missing",
        error_message="Provider result did not include a usable local output.",
        metadata=metadata,
    )


def _official_bgm_endpoint(endpoint: str | None) -> bool:
    parsed = urlparse(str(endpoint or ""))
    return parsed.scheme == "https" and parsed.hostname == "open.volcengineapi.com"


def _provider_asset_metadata(
    asset: dict[str, Any],
    provider_payload: dict[str, Any],
) -> dict[str, Any]:
    provider_asset = sanitize_context_for_llm_text(asset)
    prompt_audit = asset.get("prompt_audit") or provider_payload.get("prompt_audit")
    metadata: dict[str, Any] = {"provider_asset": provider_asset}
    for key in (
        "provider_action",
        "query_action",
        "api_version",
        "generation_version",
        "request_id",
        "callback_id",
        "callback_enabled",
        "requested_duration_seconds",
        "model_duration_limit_seconds",
        "provider_duration_seconds",
        "audio_duration_seconds",
        "source_content_type",
        "source_extension",
        "download_status",
        "download_attempted",
        "audio_quality",
        "audio_codec",
        "sample_rate",
        "channels",
        "progress",
        "provider_status",
    ):
        value = provider_asset.get(key) if isinstance(provider_asset, dict) else None
        if value is not None:
            metadata[key] = value
    if isinstance(prompt_audit, dict):
        actual_prompt = prompt_audit.get("actual_provider_request_prompt")
        if isinstance(provider_asset, dict) and isinstance(actual_prompt, str):
            provider_asset["prompt"] = actual_prompt
        metadata["prompt_audit"] = sanitize_context_for_llm_text(prompt_audit)
    if isinstance(provider_payload.get("provider_input_audit"), dict):
        metadata["provider_input_audit"] = sanitize_context_for_llm_text(
            provider_payload["provider_input_audit"]
        )
    if isinstance(provider_payload.get("provider_prompt_contract"), dict):
        metadata["provider_prompt_contract"] = sanitize_context_for_llm_text(
            provider_payload["provider_prompt_contract"]
        )
    if isinstance(provider_payload.get("prompt_sanitization_audit"), dict):
        metadata["prompt_sanitization_audit"] = sanitize_context_for_llm_text(
            provider_payload["prompt_sanitization_audit"]
        )
    if isinstance(provider_payload.get("fallback_field_completeness"), dict):
        metadata["fallback_field_completeness"] = sanitize_context_for_llm_text(
            provider_payload["fallback_field_completeness"]
        )
    if isinstance(provider_payload.get("reference_delivery_audit"), dict):
        metadata["reference_delivery_audit"] = sanitize_context_for_llm_text(
            provider_payload["reference_delivery_audit"]
        )
    if isinstance(provider_payload.get("reference_input_delivery"), dict):
        metadata["reference_input_delivery"] = sanitize_context_for_llm_text(
            provider_payload["reference_input_delivery"]
        )
    reference_wire_audit = asset.get("reference_wire_audit") or provider_payload.get(
        "reference_wire_audit"
    )
    if isinstance(reference_wire_audit, dict):
        metadata["reference_wire_audit"] = sanitize_context_for_llm_text(reference_wire_audit)
    if isinstance(provider_payload.get("quality_flags"), list):
        metadata["quality_flags"] = sanitize_context_for_llm_text(provider_payload["quality_flags"])
    return metadata


def _placeholder_bytes(media_type: str, slot_type: str) -> bytes:
    suffix = slot_type.encode("utf-8")
    if media_type == "image":
        return b"\x89PNG\r\n\x1a\n" + suffix
    if media_type == "video":
        return b"\x00\x00\x00\x18ftypmp42" + suffix
    if media_type == "audio":
        return b"RIFF\x24\x00\x00\x00WAVEfmt " + suffix
    return f"v2 {media_type} placeholder for {slot_type}\n".encode("utf-8")
