from collections.abc import Callable
from time import perf_counter
from typing import Any

from app.core.config import Settings
from app.schemas.provider_strategy import (
    ProviderAttemptTrace,
    ProviderCandidate,
    ProviderSelectionRequest,
    ProviderSelectionResult,
)
from app.schemas.workflow_nodes import WorkflowNodeRunRequest
from app.services.agent_trace import AgentTraceWriter, utc_now
from app.services.output_assets import dedupe_output_assets
from app.services.provider_capabilities import provider_for_node
from app.services.provider_strategy import ProviderStrategyService
from app.services.reference_policy import build_reference_policy, policy_error_message
from app.services.asset_flow_debug import debug_from_reference_policy
from app.services.workflow_node_errors import ReferencePolicyInputError
from app.services.workflow_node_provider_factory import build_media_provider_for_provider


CREATIVE_REFERENCE_POLICY_NODES = {
    "product-generation",
    "character-generation",
    "scene-generation",
    "storyboard",
    "storyboard-video-generation",
    "bgm",
}


class WorkflowProviderRuntime:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._provider_strategy = ProviderStrategyService(settings=settings)

    def execute_provider_strategy(
        self,
        *,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        media_type: str,
        generator: Callable[[WorkflowNodeRunRequest, Any], dict[str, Any]],
    ) -> dict[str, Any]:
        references = request.input_context.get("asset_references")
        selection = self._provider_strategy.select_candidates(
            ProviderSelectionRequest(
                workflow_id=workflow_id,
                node_id=_request_node_id(request),
                node_type=_request_node_type(request),
                media_type=media_type,  # type: ignore[arg-type]
                reference_mode=request.reference_mode,
                asset_references=references if isinstance(references, list) else [],
                provider=request.provider,
                allow_provider_fallback=request.allow_provider_fallback,
                provider_hints=request.provider_hints,
            )
        )
        attempts: list[dict[str, Any]] = []
        warnings = list(selection.warnings)
        trace_identity_certifications(
            self._settings,
            workflow_id,
            request.node_type,
            selection.identity_certifications,
        )
        if not selection.candidates:
            output = provider_strategy_failure_output(
                selection=selection,
                attempts=attempts,
                error="No provider can satisfy the selection request.",
            )
            trace_provider_strategy(self._settings, workflow_id, request.node_type, output)
            return output
        for attempt_index, candidate in enumerate(selection.candidates, start=1):
            output = self._execute_candidate(
                request=request,
                workflow_id=workflow_id,
                generator=generator,
                selection=selection,
                candidate=candidate,
                attempt_index=attempt_index,
                attempts=attempts,
                warnings=warnings,
            )
            if output is not None:
                return output
        output = provider_strategy_failure_output(
            selection=selection,
            attempts=attempts,
            error="All eligible providers failed.",
            warnings=warnings,
        )
        trace_provider_strategy(self._settings, workflow_id, request.node_type, output)
        return output

    def apply_reference_policy_to_request(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
    ) -> dict[str, Any] | None:
        return apply_reference_policy_to_request(request, workflow_id, self._settings)

    def _execute_candidate(
        self,
        *,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        generator: Callable[[WorkflowNodeRunRequest, Any], dict[str, Any]],
        selection: ProviderSelectionResult,
        candidate: ProviderCandidate,
        attempt_index: int,
        attempts: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        started_at = utc_now()
        started_counter = perf_counter()
        attempt_request = request.model_copy(deep=True)
        attempt_context = dict(attempt_request.input_context)
        apply_reference_policy_payload_to_context(attempt_context, candidate.reference_policy)
        attempt_request.input_context = attempt_context
        trace_reference_policy(
            self._settings,
            workflow_id,
            request.node_type,
            candidate.reference_policy,
        )
        try:
            provider = build_media_provider_for_provider(self._settings, candidate.provider)
            output = generator(attempt_request, provider)
            if provider_output_failed(output):
                message = provider_failure_message(output)
                self._record_failed_attempt(
                    candidate=candidate,
                    attempt_index=attempt_index,
                    status="failed",
                    reason_code="provider_failure",
                    message=message,
                    started_at=started_at,
                    started_counter=started_counter,
                    attempts=attempts,
                    warnings=warnings,
                )
                return None
            attempt = provider_attempt_trace(
                attempt_index=attempt_index,
                candidate=candidate,
                status="succeeded",
                reason_code="success",
                message="Provider succeeded.",
                started_at=started_at,
                started_counter=started_counter,
            )
            attempts.append(attempt)
            self._provider_strategy.record_success(candidate.provider)
            output = with_provider_strategy_metadata(
                output,
                selection=selection,
                selected_provider=candidate.provider,
                attempts=attempts,
                warnings=warnings,
            )
            trace_provider_strategy(self._settings, workflow_id, request.node_type, output)
            return output
        except TimeoutError as exc:
            reason_code = "provider_timeout"
            message = str(exc) or "Provider timed out."
        except Exception as exc:  # noqa: BLE001 - fallback records provider failures.
            reason_code = "provider_exception"
            message = str(exc) or "Provider failed."
        self._record_failed_attempt(
            candidate=candidate,
            attempt_index=attempt_index,
            status="failed",
            reason_code=reason_code,
            message=message,
            started_at=started_at,
            started_counter=started_counter,
            attempts=attempts,
            warnings=warnings,
        )
        return None

    def _record_failed_attempt(
        self,
        *,
        candidate: ProviderCandidate,
        attempt_index: int,
        status: str,
        reason_code: str,
        message: str,
        started_at: Any,
        started_counter: float,
        attempts: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
    ) -> None:
        attempt = provider_attempt_trace(
            attempt_index=attempt_index,
            candidate=candidate,
            status=status,
            reason_code=reason_code,
            message=message,
            started_at=started_at,
            started_counter=started_counter,
        )
        attempts.append(attempt)
        warnings.append(provider_attempt_warning(attempt))
        self._provider_strategy.record_failure(candidate.provider, reason_code)


def apply_reference_policy_to_request(
    request: WorkflowNodeRunRequest,
    workflow_id: str,
    settings: Settings,
) -> dict[str, Any] | None:
    if request.node_type not in CREATIVE_REFERENCE_POLICY_NODES:
        return None
    references = request.input_context.get("asset_references")
    if not isinstance(references, list) or not references:
        return None
    provider = provider_for_node(request.node_type, media_mode=settings.media_mode)
    policy = build_reference_policy(
        references,
        node_type=request.node_type,
        provider=provider,
        request_reference_mode=request.reference_mode,
    )
    payload = policy.model_dump(mode="json")
    request.input_context["reference_policy"] = payload
    request.input_context["accepted_reference_assets"] = payload["accepted_assets"]
    request.input_context["prompt_only_reference_assets"] = payload["prompt_only_assets"]
    request.input_context["rejected_reference_assets"] = payload["rejected_assets"]
    request.input_context["reference_assets"] = payload["accepted_assets"]
    request.input_context["provider_reference_plan"] = payload.get("reference_plan") or {}
    request.input_context["asset_flow_debug"] = debug_from_reference_policy(
        input_references=references,
        policy=payload,
        selected_provider=provider,
        failure_stage="reference_policy" if payload["errors"] else "none",
    )
    if payload["warnings"]:
        request.input_context["reference_policy_warnings"] = payload["warnings"]
    trace_reference_policy(settings, workflow_id, request.node_type, payload)
    if payload["errors"]:
        raise ReferencePolicyInputError(payload)
    return payload


def trace_reference_policy(
    settings: Settings,
    workflow_id: str,
    node_type: str,
    policy: dict[str, Any],
) -> None:
    started_at = utc_now()
    error = policy_error_message(policy) if policy.get("errors") else None
    AgentTraceWriter(settings.media_data_dir, workflow_id).append(
        agent="Reference Policy",
        model=None,
        prompt=f"Build reference policy for {node_type}.",
        output=policy,
        error=error,
        started_at=started_at,
        finished_at=utc_now(),
        duration_ms=0,
        metadata={
            "trace_role": "reference_policy",
            "node_id": node_type,
            "status": "failed" if policy.get("errors") else "completed",
            **policy,
        },
    )


def accepted_reference_assets(context: dict[str, Any]) -> list[dict[str, Any]]:
    assets = context.get("accepted_reference_assets")
    return (
        [asset for asset in assets if isinstance(asset, dict)] if isinstance(assets, list) else []
    )


def provider_input_assets(
    input_assets: list[dict[str, Any]],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    policy = context.get("reference_policy")
    if not isinstance(policy, dict):
        return input_assets
    non_library_assets = [
        asset for asset in input_assets if not _is_asset_library_reference_asset(asset)
    ]
    return dedupe_output_assets([*non_library_assets, *accepted_reference_assets(context)])


def output_with_reference_policy(
    output: dict[str, Any],
    reference_policy: dict[str, Any] | None,
) -> dict[str, Any]:
    if not reference_policy:
        return output
    references = output.get("asset_references")
    if not isinstance(references, list):
        references = [
            *(reference_policy.get("accepted_assets") or []),
            *(reference_policy.get("prompt_only_assets") or []),
            *(reference_policy.get("rejected_assets") or []),
        ]
    debug = debug_from_reference_policy(
        input_references=references,
        policy=reference_policy,
        selected_provider=reference_policy.get("provider"),
        provider_attempts=output.get("provider_attempts")
        if isinstance(output.get("provider_attempts"), list)
        else [],
        failure_stage="reference_policy" if reference_policy.get("errors") else "none",
    )
    return {
        **output,
        "reference_policy": reference_policy,
        "provider_reference_plan": reference_policy.get("reference_plan") or {},
        "asset_flow_debug": output.get("asset_flow_debug") or debug,
    }


def apply_reference_policy_payload_to_context(
    context: dict[str, Any],
    reference_policy: dict[str, Any],
) -> None:
    context["reference_policy"] = reference_policy
    context["accepted_reference_assets"] = reference_policy.get("accepted_assets") or []
    context["prompt_only_reference_assets"] = reference_policy.get("prompt_only_assets") or []
    context["rejected_reference_assets"] = reference_policy.get("rejected_assets") or []
    context["reference_assets"] = reference_policy.get("accepted_assets") or []
    context["provider_reference_plan"] = reference_policy.get("reference_plan") or {}
    references = context.get("asset_references")
    context["asset_flow_debug"] = debug_from_reference_policy(
        input_references=references if isinstance(references, list) else [],
        policy=reference_policy,
        selected_provider=reference_policy.get("provider"),
        failure_stage="reference_policy" if reference_policy.get("errors") else "none",
    )
    warnings = reference_policy.get("warnings")
    if warnings:
        context["reference_policy_warnings"] = warnings


def provider_output_failed(output: dict[str, Any]) -> bool:
    return str(output.get("status") or "").lower() in {"failed", "failure", "error"}


def provider_failure_message(output: dict[str, Any]) -> str:
    for key in ("error", "message", "detail"):
        value = output.get(key)
        if value not in (None, ""):
            return str(value)
    return "Provider returned failed output."


def provider_attempt_trace(
    *,
    attempt_index: int,
    candidate: ProviderCandidate,
    status: str,
    reason_code: str,
    message: str,
    started_at: Any,
    started_counter: float,
) -> dict[str, Any]:
    return ProviderAttemptTrace(
        attempt_index=attempt_index,
        provider=candidate.provider,
        status=status,  # type: ignore[arg-type]
        reason_code=reason_code,  # type: ignore[arg-type]
        message=message,
        reference_policy=candidate.reference_policy,
        identity_certification=candidate.identity_certification,
        started_at=started_at.isoformat(),
        ended_at=utc_now().isoformat(),
        duration_ms=round((perf_counter() - started_counter) * 1000),
    ).model_dump(mode="json")


def provider_attempt_warning(attempt: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": attempt.get("reason_code") or "provider_failure",
        "provider": attempt.get("provider"),
        "message": attempt.get("message") or "Provider attempt failed.",
    }


def with_provider_strategy_metadata(
    output: dict[str, Any],
    *,
    selection: ProviderSelectionResult,
    selected_provider: str,
    attempts: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    provider_warnings = dedupe_provider_warnings([*selection.warnings, *warnings])
    fallback_used = bool(attempts) and attempts[0].get("provider") != selected_provider
    provider_strategy = provider_strategy_payload(
        selection,
        selected_provider=selected_provider,
        attempts=attempts,
        warnings=provider_warnings,
        fallback_used=fallback_used,
        status="completed",
    )
    merged = {
        **output,
        "selected_provider": selected_provider,
        "provider_strategy": provider_strategy,
        "provider_attempts": attempts,
        "provider_warnings": provider_warnings,
        "fallback_warnings": provider_warnings,
    }
    identity_certification = selected_candidate_identity_certification(selection, selected_provider)
    if identity_certification and identity_certification.get("required"):
        merged["identity_certification"] = identity_certification
    return output_with_reference_policy(
        merged,
        selected_candidate_reference_policy(selection, selected_provider),
    )


def provider_strategy_failure_output(
    *,
    selection: ProviderSelectionResult,
    attempts: list[dict[str, Any]],
    error: str,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    provider_warnings = dedupe_provider_warnings([*selection.warnings, *(warnings or [])])
    attempted_providers = [str(attempt.get("provider")) for attempt in attempts]
    provider_strategy = provider_strategy_payload(
        selection,
        selected_provider=None,
        attempts=attempts,
        warnings=provider_warnings,
        fallback_used=len(set(attempted_providers)) > 1,
        status="failed",
    )
    output = {
        "status": "failed",
        "error": error,
        "selected_provider": None,
        "provider_strategy": provider_strategy,
        "provider_attempts": attempts,
        "provider_warnings": provider_warnings,
        "fallback_warnings": provider_warnings,
        "failure_stage": "provider_call" if attempts else "provider_selection",
    }
    product_error_code = product_reference_error_code(provider_warnings)
    if product_error_code:
        output["error_code"] = product_error_code
        output["error"] = f"{product_error_code}: {error}"
    identity_certification = failed_identity_certification(selection)
    if identity_certification:
        output["identity_certification"] = identity_certification
    output["user_explainable_reason"] = (
        "Provider was called but returned a failure."
        if attempts
        else "No provider satisfied the current constraints, so no model was called."
    )
    output["asset_flow_debug"] = {
        "input_reference_count": 0,
        "display_asset_count": 0,
        "prompt_context_asset_count": 0,
        "provider_reference_asset_count": 0,
        "prompt_only_asset_count": 0,
        "rejected_reference_count": 0,
        "provider_attempt_count": len(attempts),
        "selected_provider": None,
        "failure_stage": output["failure_stage"],
        "user_explainable_reason": output["user_explainable_reason"],
        "warnings": provider_warnings,
    }
    return output


def product_reference_error_code(warnings: list[dict[str, Any]]) -> str:
    for warning in warnings:
        code = str(warning.get("code") or "")
        if code in {
            "product_reference_required",
            "product_reference_missing",
            "product_reference_provider_unsupported",
            "product_reference_dropped",
        }:
            return code
    return ""


def provider_strategy_payload(
    selection: ProviderSelectionResult,
    *,
    selected_provider: str | None,
    attempts: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    fallback_used: bool,
    status: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "selected_provider": selected_provider,
        "initial_selected_provider": selection.selected_provider,
        "fallback_allowed": selection.fallback_allowed,
        "fallback_used": fallback_used,
        "selection_reason": selection.selection_reason,
        "provider_hints": selection.provider_hints,
        "max_attempts": selection.max_attempts,
        "attempted_providers": [
            str(attempt.get("provider"))
            for attempt in attempts
            if attempt.get("provider") not in (None, "")
        ],
        "candidates": [
            {
                "provider": candidate.provider,
                "media_type": candidate.media_type,
                "priority": candidate.priority,
                "health": candidate.health.model_dump(mode="json"),
                "reference_policy": candidate.reference_policy,
                "provider_reference_plan": candidate.provider_reference_plan,
                "identity_certification": candidate.identity_certification,
            }
            for candidate in selection.candidates
        ],
        "warnings": warnings,
    }


def selected_candidate_reference_policy(
    selection: ProviderSelectionResult,
    selected_provider: str,
) -> dict[str, Any] | None:
    for candidate in selection.candidates:
        if candidate.provider == selected_provider:
            return candidate.reference_policy
    return None


def selected_candidate_identity_certification(
    selection: ProviderSelectionResult,
    selected_provider: str,
) -> dict[str, Any] | None:
    for candidate in selection.candidates:
        if candidate.provider == selected_provider:
            return candidate.identity_certification
    return None


def failed_identity_certification(
    selection: ProviderSelectionResult,
) -> dict[str, Any] | None:
    for certification in selection.identity_certifications:
        if certification.get("errors"):
            return certification
    for certification in selection.identity_certifications:
        if certification.get("required"):
            return certification
    return None


def trace_identity_certifications(
    settings: Settings,
    workflow_id: str,
    node_type: str,
    certifications: list[dict[str, Any]],
) -> None:
    writer = AgentTraceWriter(settings.media_data_dir, workflow_id)
    for certification in certifications:
        if not certification.get("required"):
            continue
        started_at = utc_now()
        errors = certification.get("errors")
        error = None
        if isinstance(errors, list) and errors:
            error = ", ".join(
                str(item.get("code") or "identity_certification_required")
                for item in errors
                if isinstance(item, dict)
            )
        writer.append(
            agent="Identity Certification",
            model=None,
            prompt=f"Check identity certification for {node_type}.",
            output=certification,
            error=error,
            started_at=started_at,
            finished_at=utc_now(),
            duration_ms=0,
            metadata={
                "trace_role": "identity_certification",
                "node_id": node_type,
                **certification,
            },
        )


def trace_provider_strategy(
    settings: Settings,
    workflow_id: str,
    node_type: str,
    output: dict[str, Any],
) -> None:
    started_at = utc_now()
    status = str(output.get("status") or "completed").lower()
    error = str(output.get("error")) if status == "failed" and output.get("error") else None
    provider_strategy = output.get("provider_strategy")
    provider_attempts = output.get("provider_attempts")
    trace_output = {
        "provider_strategy": provider_strategy if isinstance(provider_strategy, dict) else {},
        "provider_attempts": provider_attempts if isinstance(provider_attempts, list) else [],
        "selected_provider": output.get("selected_provider"),
    }
    AgentTraceWriter(settings.media_data_dir, workflow_id).append(
        agent="Provider Strategy",
        model=None,
        prompt=f"Select and execute provider for {node_type}.",
        output=trace_output,
        error=error,
        started_at=started_at,
        finished_at=utc_now(),
        duration_ms=0,
        metadata={
            "trace_role": "provider_strategy",
            "node_id": node_type,
            "status": "failed" if status == "failed" else "completed",
            **trace_output,
        },
    )


def dedupe_provider_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for warning in warnings:
        key = (
            str(warning.get("code") or ""),
            str(warning.get("provider") or ""),
            str(warning.get("message") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(warning)
    return deduped


def _request_node_id(request: WorkflowNodeRunRequest) -> str:
    return str(request.node_id or request.node_type or "")


def _request_node_type(request: WorkflowNodeRunRequest) -> str:
    return str(request.node_type or request.node_id or "")


def _is_asset_library_reference_asset(asset: Any) -> bool:
    return isinstance(asset, dict) and (
        asset.get("source_type") in {"asset_library", "canvas_asset"}
        or asset.get("source_node_id") in {"asset_library", "canvas_asset"}
        or asset.get("source") in {"asset_library", "canvas_asset"}
    )
