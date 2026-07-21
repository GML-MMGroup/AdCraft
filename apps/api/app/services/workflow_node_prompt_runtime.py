from typing import Any

# V1/legacy compatibility only. V2 high-risk provider, repair, fallback,
# and storyboard detail prompt paths must not import this module.

from app.core.config import Settings
from app.schemas.prompt_optimization import PromptOptimizationRequest
from app.services.asset_flow_debug import build_asset_flow_debug, explain_asset_flow_failure
from app.schemas.workflow_nodes import WorkflowNodeRunRequest
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text_with_warnings
from app.services.prompt_optimizer_context import prompt_optimizer_context_summaries
from app.services.workflow_prompt_optimizer import (
    WorkflowPromptOptimizerError,
    WorkflowPromptOptimizerService,
)


def _optimize_generation_prompt(
    request: WorkflowNodeRunRequest,
    input_assets: list[dict[str, Any]],
    workflow_id: str,
    settings: Settings,
) -> dict[str, Any]:
    provider_reference_assets = [
        asset
        for asset in request.input_context.get("provider_reference_assets", [])
        if isinstance(asset, dict)
    ]
    unsupported_provider_references = [
        asset
        for asset in provider_reference_assets
        if asset.get("provider_reference_unsupported")
        or asset.get("provider_reference_supported") is False
    ]
    if unsupported_provider_references:
        request.input_context["provider_reference_unsupported"] = True
        request.input_context["provider_reference_unsupported_assets"] = [
            str(asset.get("asset_id") or "")
            for asset in unsupported_provider_references
            if asset.get("asset_id")
        ]
    try:
        optimization = WorkflowPromptOptimizerService(settings).optimize(
            _prompt_optimization_request(
                request,
                input_assets=input_assets,
                workflow_id=workflow_id,
                settings=settings,
            )
        )
    except WorkflowPromptOptimizerError as exc:
        error = f"{exc.code}: {exc}"
        request.input_context["optimizer_error_code"] = exc.code
        request.input_context["optimizer_error"] = str(exc)
        return {
            "status": "failed",
            "error": error,
            "error_code": exc.code,
            "failure_stage": "prompt_optimizer",
            "user_explainable_reason": explain_asset_flow_failure(exc.code),
            "asset_flow_debug": build_asset_flow_debug(
                input_references=request.input_context.get("asset_references")
                if isinstance(request.input_context.get("asset_references"), list)
                else [],
                display_assets=request.input_context.get("display_input_assets")
                if isinstance(request.input_context.get("display_input_assets"), list)
                else [],
                prompt_context_assets=request.input_context.get("prompt_context_assets")
                if isinstance(request.input_context.get("prompt_context_assets"), list)
                else [],
                provider_reference_assets=request.input_context.get("provider_reference_assets")
                if isinstance(request.input_context.get("provider_reference_assets"), list)
                else [],
                prompt_only_assets=request.input_context.get("prompt_only_reference_assets")
                if isinstance(request.input_context.get("prompt_only_reference_assets"), list)
                else [],
                rejected_assets=request.input_context.get("rejected_reference_assets")
                if isinstance(request.input_context.get("rejected_reference_assets"), list)
                else [],
                selected_provider=request.provider,
                failure_stage="prompt_optimizer",
                user_explainable_reason=explain_asset_flow_failure(exc.code),
                warnings=request.input_context.get("optimizer_warnings")
                if isinstance(request.input_context.get("optimizer_warnings"), list)
                else [],
            ),
            "optimizer_warnings": request.input_context.get("optimizer_warnings", []),
            "output_assets": [],
            "assets": [],
        }
    request.input_context["optimized_generation_prompt"] = optimization.optimized_generation_prompt
    request.input_context["provider_prompt"] = optimization.provider_prompt
    request.input_context["negative_prompt"] = optimization.negative_prompt
    request.input_context["optimizer_agent"] = optimization.optimizer_agent
    request.input_context["selected_skill_ids"] = optimization.selected_skill_ids
    request.input_context["optimizer_mock_mode"] = optimization.mock_mode
    request.input_context["optimizer_warnings"] = optimization.warnings
    request.input_context["optimizer_quality_notes"] = optimization.quality_notes
    request.input_context["optimizer_asset_references"] = optimization.asset_references
    if "user_prompt" not in request.input_context:
        request.input_context["user_prompt"] = ""
    reference_policy = request.input_context.get("reference_policy")
    output = {
        "optimized_generation_prompt": optimization.optimized_generation_prompt,
        "provider_prompt": optimization.provider_prompt,
        "negative_prompt": optimization.negative_prompt,
        "asset_references": optimization.asset_references,
        "reference_requirements": optimization.reference_requirements,
        "provider_parameters": optimization.provider_parameters,
        "continuity_constraints": optimization.continuity_constraints,
        "quality_notes": optimization.quality_notes,
        "optimizer_agent": optimization.optimizer_agent,
        "selected_skill_ids": optimization.selected_skill_ids,
        "mock_mode": optimization.mock_mode,
        "warnings": optimization.warnings,
        "status": "optimized",
        "provider_reference_unsupported": bool(unsupported_provider_references),
        "provider_reference_unsupported_assets": request.input_context.get(
            "provider_reference_unsupported_assets", []
        ),
    }
    if isinstance(reference_policy, dict):
        output["reference_policy"] = reference_policy
    return output


def _prompt_optimization_failed(output: dict[str, Any]) -> bool:
    return str(output.get("status") or "").lower() == "failed" and str(
        output.get("error_code") or ""
    ).startswith("prompt_optimizer_")


def _prompt_optimization_request(
    request: WorkflowNodeRunRequest,
    *,
    input_assets: list[dict[str, Any]],
    workflow_id: str,
    settings: Settings,
) -> PromptOptimizationRequest:
    context = request.input_context
    sanitized_context, context_warnings = _sanitize_for_optimizer_request(context)
    sanitized_input_assets, asset_warnings = _sanitize_for_optimizer_request(input_assets)
    director_context = _director_context_from_prompt_context(sanitized_context)
    node_type = _request_node_type(request)
    asset_references = (
        sanitized_context.get("asset_references")
        if isinstance(sanitized_context.get("asset_references"), list)
        else []
    )
    media_type = _provider_media_type_for_node(node_type)
    summaries = prompt_optimizer_context_summaries(
        settings=settings,
        workflow_id=workflow_id,
        node_id=_request_node_id(request),
        node_type=node_type,
        input_context=sanitized_context,
        media_type=media_type,
        media_mode=settings.media_mode,
        request_provider=request.provider,
        reference_mode=request.reference_mode,
        asset_references=list(asset_references),
    )
    return PromptOptimizationRequest(
        workflow_id=workflow_id,
        node_id=_request_node_id(request),
        node_type=node_type,
        mode="optimize_only" if request.optimize_only else "generate",
        user_prompt=_string_context_value(sanitized_context, "user_prompt"),
        system_suggested_prompt=_string_context_value(sanitized_context, "system_suggested_prompt"),
        materialized_prompt=_string_context_value(sanitized_context, "materialized_prompt"),
        override_prompt=request.override_prompt
        or _string_context_value(sanitized_context, "override_prompt"),
        director_context=director_context,
        resolved_input_context=dict(
            sanitized_context.get("resolved_input_context") or sanitized_context
        ),
        resolved_input_assets=list(
            sanitized_context.get("resolved_input_assets")
            if isinstance(sanitized_context.get("resolved_input_assets"), list)
            else sanitized_input_assets
        ),
        upstream_structured_outputs={
            key: value
            for key, value in sanitized_context.items()
            if isinstance(value, dict)
            and key
            in {
                "script",
                "character_design",
                "scene_design",
                "storyboard",
                "storyboard_video",
                "bgm",
            }
        },
        asset_references=list(asset_references),
        provider_media_type=media_type,
        reference_policy_summary=summaries.reference_policy_summary,
        provider_capability_summary=summaries.provider_capability_summary,
        identity_certification_summary=summaries.identity_certification_summary,
        selected_provider=summaries.selected_provider,
        allow_optimizer_fallback=request.allow_optimizer_fallback,
        warnings=[*context_warnings, *asset_warnings],
    )


def _director_context_from_prompt_context(context: dict[str, Any]) -> dict[str, Any]:
    for key in ("director_context", "director_context_summary"):
        value = context.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _sanitize_for_optimizer_request(value: Any) -> tuple[Any, list[dict[str, Any]]]:
    try:
        return sanitize_context_for_llm_text_with_warnings(value)
    except Exception as exc:
        raise WorkflowPromptOptimizerError(
            "llm_context_sanitization_failed",
            "Failed to sanitize prompt optimizer context for LLM text.",
        ) from exc


def _string_context_value(context: dict[str, Any], key: str) -> str | None:
    value = context.get(key)
    return value if isinstance(value, str) else None


def _provider_media_type_for_node(node_type: str) -> str | None:
    if node_type in {
        "product-generation",
        "character-generation",
        "scene-generation",
        "storyboard",
    }:
        return "image"
    if node_type == "storyboard-video-generation":
        return "video"
    if node_type == "bgm":
        return "audio"
    return None


def _prompt_seed(request: WorkflowNodeRunRequest) -> str:
    context = request.input_context
    for key in ("user_prompt",):
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            return value
    if request.override_prompt:
        return request.override_prompt
    for key in ("applied_optimized_prompt", "system_suggested_prompt", "materialized_prompt"):
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return f"Create media for {request.node_type}."


def _request_node_id(request: WorkflowNodeRunRequest) -> str:
    return str(request.node_id or request.node_type or "")


def _request_node_type(request: WorkflowNodeRunRequest) -> str:
    return str(request.node_type or request.node_id or "")


optimize_generation_prompt = _optimize_generation_prompt
prompt_optimization_failed = _prompt_optimization_failed
prompt_seed = _prompt_seed
