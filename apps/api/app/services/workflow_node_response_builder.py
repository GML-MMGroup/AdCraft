from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.schemas.workflow_nodes import WorkflowNodeRunRequest, WorkflowNodeRunResponse
from app.schemas.workflow_revisions import WorkflowRevisionState
from app.services.asset_flow_debug import build_asset_flow_debug, explain_asset_flow_failure
from app.services.media_paths import with_public_urls
from app.services.output_assets import dedupe_output_assets
from app.services.workflow_input_resolver import (
    WorkflowInputResolutionError,
    WorkflowNodeInputResolver,
)
from app.services.workflow_node_asset_derivation import _apply_library_derivation_metadata
from app.services.workflow_node_catalog import OUTPUT_CONTRACT_MEDIA_NODES
from app.services.workflow_node_output_contract import (
    extract_output_assets as _extract_output_assets,
    node_run_error_from_output as _node_run_error_from_output,
    node_run_is_waiting as _node_run_is_waiting,
    node_run_status_from_output as _node_run_status_from_output,
    sanitize_node_output as _sanitize_node_output,
    with_node_instance_identity as _with_node_instance_identity,
    with_node_output_contract as _with_node_output_contract,
)
from app.services.workflow_node_run_preparation import (
    _has_request_asset_references,
    _is_asset_reference_asset,
)
from app.services.workflow_quality_review import WorkflowQualityReviewService


class WorkflowNodeResponseBuilderMixin:
    def _execute_and_normalize_output(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        node_id: str,
        node_type: str,
        settings: Settings,
        input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        output = self._execute_node(request, workflow_id, settings, input_assets)
        output = _sanitize_node_output(node_type, output, settings.media_data_dir)
        output = _with_node_output_contract(output, node_type, workflow_id)
        output = _with_node_instance_identity(output, node_id, node_type)
        return _apply_library_derivation_metadata(output, request.input_context)

    def _run_response_from_output(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        node_id: str,
        node_type: str,
        node_run_id: str,
        input_assets: list[dict[str, Any]],
        output: dict[str, Any],
        settings: Settings,
    ) -> WorkflowNodeRunResponse:
        output_assets = with_public_urls(_extract_output_assets(output))
        optimize_only_result = _is_optimize_only_result(request, output)
        candidate_pending_result = _is_final_candidate_pending_result(node_type, output)
        if optimize_only_result:
            output_assets = []
        elif _media_output_contract_failed(node_type, output, output_assets):
            output = _with_output_contract_failure(output, request)
        result_status = _node_run_status_from_output(node_type, output, settings.media_data_dir)
        result_error = _node_run_error_from_output(node_type, output)
        if not optimize_only_result and result_status != "failed":
            output, output_assets, _quality_summary = WorkflowQualityReviewService(
                settings
            ).review_node_output(
                workflow_id,
                node_id,
                node_type,
                output,
                output_assets,
                request.input_context,
            )
        return WorkflowNodeRunResponse(
            workflow_id=workflow_id,
            node_id=node_id,
            node_run_id=node_run_id,
            node_type=node_type,
            status=result_status,
            output=output,
            input_context=request.input_context,
            input_assets=input_assets,
            output_assets=output_assets,
            error=result_error,
            stale=_node_run_is_waiting(node_type, output, settings.media_data_dir),
            has_active_output=(
                result_status == "completed"
                and not candidate_pending_result
                and bool(output or output_assets)
            ),
        )

    def _failed_run_response(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        node_id: str,
        node_type: str,
        node_run_id: str,
        input_assets: list[dict[str, Any]],
        *,
        output: dict[str, Any],
        error: str,
    ) -> WorkflowNodeRunResponse:
        return WorkflowNodeRunResponse(
            workflow_id=workflow_id,
            node_id=node_id,
            node_run_id=node_run_id,
            node_type=node_type,
            status="failed",
            output=output,
            input_context=request.input_context,
            input_assets=input_assets,
            output_assets=[],
            error=error,
            stale=True,
            has_active_output=False,
        )

    def _attach_resolved_inputs(
        self,
        result: WorkflowNodeRunResponse,
        request: WorkflowNodeRunRequest,
        input_assets: list[dict[str, Any]],
        settings: Settings,
    ) -> None:
        result.resolved_input_context = request.input_context
        result.resolved_input_assets = input_assets
        try:
            resolved = WorkflowNodeInputResolver(settings).resolve_node_inputs(
                result.workflow_id,
                result.node_id,
            )
        except WorkflowInputResolutionError:
            return
        result.resolved_input_context = resolved.resolved_input_context
        result.resolved_input_assets = resolved.resolved_input_assets
        result.asset_references = resolved.asset_references
        result.prompt_context_assets = resolved.prompt_context_assets
        result.provider_reference_assets = resolved.provider_reference_assets
        result.display_input_assets = resolved.display_input_assets
        result.materialized_prompt = resolved.materialized_prompt
        result.materialized_assets = resolved.materialized_assets
        result.source_mappings = resolved.source_mappings
        result.resolved_prompt_preview = resolved.resolved_prompt_preview
        result.resolved_prompt_with_assets = resolved.resolved_prompt_with_assets
        result.effective_prompt = resolved.effective_prompt
        result.missing_inputs = resolved.missing_inputs
        result.stale_upstream_nodes = resolved.stale_upstream_nodes
        result.locked_upstream_nodes = resolved.locked_upstream_nodes
        if _has_request_asset_references(request):
            for field_name in (
                "asset_references",
                "prompt_context_assets",
                "provider_reference_assets",
                "display_input_assets",
            ):
                value = request.input_context.get(field_name)
                if isinstance(value, list):
                    setattr(result, field_name, value)
                    result.resolved_input_context[field_name] = value
            result.resolved_input_assets = dedupe_output_assets(
                [
                    asset
                    for asset in result.resolved_input_assets
                    if not _is_asset_reference_asset(asset)
                ]
                + [asset for asset in request.input_assets if _is_asset_reference_asset(asset)]
            )
            request_mappings = [
                mapping
                for mapping in request.input_context.get("source_mappings", [])
                if isinstance(mapping, dict)
                and mapping.get("source_type") in {"asset_library", "canvas_asset"}
            ]
            if request_mappings:
                result.source_mappings = [
                    mapping
                    for mapping in result.source_mappings
                    if mapping.get("source_type") not in {"asset_library", "canvas_asset"}
                ] + request_mappings
                result.resolved_input_context["source_mappings"] = result.source_mappings


def _node_response_from_revision_state(
    state: WorkflowRevisionState,
    *,
    existing_result: WorkflowNodeRunResponse | None,
    workflow_id: str,
    node_id: str,
    node_type: str,
    node_run_id: str,
) -> WorkflowNodeRunResponse:
    if isinstance(state.node, dict) and state.node:
        return WorkflowNodeRunResponse.model_validate(state.node)
    status = "failed" if state.status in {"failed", "cancelled"} else "waiting"
    output = dict(state.candidate_output or {})
    if state.candidate_assets:
        output.setdefault("assets", state.candidate_assets)
        output.setdefault("output_assets", state.candidate_assets)
        output.setdefault("status", "candidate_pending")
        output["revision_id"] = state.revision_id
        output["acceptance_status"] = state.acceptance_status
        output["generation_status"] = state.generation_status or state.status
    output_assets = list(state.candidate_assets) if state.candidate_assets else []
    return WorkflowNodeRunResponse(
        workflow_id=workflow_id,
        node_id=node_id,
        node_run_id=node_run_id,
        node_type=node_type,
        status=status,
        output=output,
        input_context=dict(existing_result.input_context) if existing_result else {},
        input_assets=list(existing_result.input_assets) if existing_result else [],
        output_assets=output_assets,
        error=state.error,
        stale=True,
        has_active_output=False,
    )


def _is_final_candidate_pending_result(node_type: str, output: dict[str, Any]) -> bool:
    return (
        node_type == "final-composition"
        and str(output.get("status") or "").lower() == "candidate_pending"
    )


def _media_output_contract_failed(
    node_type: str,
    output: dict[str, Any],
    output_assets: list[dict[str, Any]],
) -> bool:
    if node_type not in OUTPUT_CONTRACT_MEDIA_NODES:
        return False
    if str(output.get("status") or "").lower() in {"failed", "optimized", "submitted", "running"}:
        return False
    return not output_assets


def _with_output_contract_failure(
    output: dict[str, Any],
    request: WorkflowNodeRunRequest,
) -> dict[str, Any]:
    provider_attempts = (
        output.get("provider_attempts") if isinstance(output.get("provider_attempts"), list) else []
    )
    warnings = (
        output.get("provider_warnings") if isinstance(output.get("provider_warnings"), list) else []
    )
    reason = explain_asset_flow_failure("output_assets_empty")
    return {
        **output,
        "status": "failed",
        "error_code": "output_assets_empty",
        "error": "output_assets_empty: provider returned no registerable media assets.",
        "failure_stage": "output_contract",
        "user_explainable_reason": reason,
        "assets": [],
        "output_assets": [],
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
            provider_reference_assets=request.input_context.get("accepted_reference_assets")
            if isinstance(request.input_context.get("accepted_reference_assets"), list)
            else [],
            prompt_only_assets=request.input_context.get("prompt_only_reference_assets")
            if isinstance(request.input_context.get("prompt_only_reference_assets"), list)
            else [],
            rejected_assets=request.input_context.get("rejected_reference_assets")
            if isinstance(request.input_context.get("rejected_reference_assets"), list)
            else [],
            provider_attempts=provider_attempts,
            selected_provider=output.get("selected_provider")
            if isinstance(output.get("selected_provider"), str)
            else None,
            failure_stage="output_contract",
            user_explainable_reason=reason,
            warnings=warnings,
        ),
    }


def _is_optimize_only_result(
    request: WorkflowNodeRunRequest,
    output: dict[str, Any],
) -> bool:
    return bool(request.optimize_only) and str(output.get("status") or "").lower() == "optimized"
