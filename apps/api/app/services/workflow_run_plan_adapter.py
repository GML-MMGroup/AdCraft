from typing import Any

from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.ad_workflow import AdWorkflowGenerateRequest
from app.schemas.agent_outputs import BgmOutput
from app.schemas.workflow_graph import WorkflowGraph, WorkflowGraphNode
from app.schemas.workflow_nodes import WorkflowRunRequest, WorkflowRunResponse
from app.services.input_modality import selected_asset_summary
from app.services.workflow_graph import _apply_run_result_to_graph_node
from app.services.workflow_node_errors import WorkflowNodeInputError
from app.services.workflow_nodes import NODE_CATALOG
from app.services.workflow_run_inputs import output
from app.services.workflow_run_response_builder import build_workflow_run_response
from app.services.workflow_state import load_workflow_plan


class WorkflowRunPlanAdapter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def ad_request_from_graph_or_plan(
        self,
        workflow_id: str,
        graph: WorkflowGraph,
    ) -> AdWorkflowGenerateRequest:
        return ad_request_from_graph_or_plan(self._settings.media_data_dir, workflow_id, graph)

    def selected_plan_node_types(
        self,
        plan_node_types: list[str],
        request: WorkflowRunRequest,
    ) -> list[str]:
        return selected_plan_node_types(plan_node_types, request)

    def selected_node_types(self, request: WorkflowRunRequest) -> list[str]:
        return selected_node_types(request)

    def requirements_output(self, request: AdWorkflowGenerateRequest) -> dict[str, Any]:
        return requirements_output(request)

    def product_design_output(
        self,
        request: AdWorkflowGenerateRequest,
        requirements: dict[str, Any],
    ) -> dict[str, Any]:
        return product_design_output(request, requirements)

    def creative_direction_output(
        self,
        request: AdWorkflowGenerateRequest,
        active: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        return creative_direction_output(request, active)

    def bgm_output(
        self,
        request: AdWorkflowGenerateRequest,
        active: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        return bgm_output(request, active)

    def fallback_run_is_no_op(
        self,
        selected_node_types: list[str],
        active: dict[str, dict[str, Any]],
        request: WorkflowRunRequest,
    ) -> bool:
        return fallback_run_is_no_op(
            selected_node_types,
            active,
            request,
            self._settings.media_data_dir,
        )

    def fallback_no_op_response(
        self,
        *,
        workflow_id: str,
        execution_id: str,
        request: WorkflowRunRequest,
        skipped_nodes: list[str],
        media_status: Any,
    ) -> WorkflowRunResponse:
        return fallback_no_op_response(
            workflow_id=workflow_id,
            execution_id=execution_id,
            request=request,
            skipped_nodes=skipped_nodes,
            media_status=media_status,
        )

    def fallback_frontier_node_id(
        self,
        request: WorkflowRunRequest,
        selected_node_types: list[str],
    ) -> str:
        return fallback_frontier_node_id(request, selected_node_types)

    def effective_graph_run_mode(self, request: WorkflowRunRequest) -> str:
        return effective_graph_run_mode(request)

    def update_graph_node_from_result(
        self,
        node: WorkflowGraphNode,
        result: dict[str, Any],
    ) -> None:
        update_graph_node_from_result(node, result)


def ad_request_from_graph_or_plan(
    data_dir: Any,
    workflow_id: str,
    graph: WorkflowGraph,
) -> AdWorkflowGenerateRequest:
    raw_ad_request: Any = graph.ad_request
    if not raw_ad_request:
        plan = load_workflow_plan(data_dir, workflow_id)
        plan_ad_request = plan.get("ad_request") if plan else None
        if plan_ad_request:
            raw_ad_request = plan_ad_request
            graph.ad_request = plan_ad_request
    return validate_ad_request_payload(
        workflow_id,
        raw_ad_request,
        source="workflow graph or workflow plan",
    )


def selected_plan_node_types(
    plan_node_types: list[str],
    request: WorkflowRunRequest,
) -> list[str]:
    if request.mode == "force_rerun_all":
        return plan_node_types
    if request.start_node_id is None:
        return plan_node_types
    if request.start_node_id not in plan_node_types:
        raise WorkflowNodeInputError(f"unsupported start_node_id: {request.start_node_id}")
    start_index = plan_node_types.index(request.start_node_id)
    if request.run_downstream:
        return plan_node_types[start_index:]
    return [request.start_node_id]


def selected_node_types(request: WorkflowRunRequest) -> list[str]:
    node_types = [node.node_type for node in NODE_CATALOG]
    if request.mode == "force_rerun_all":
        return node_types
    if request.start_node_id is None:
        return node_types
    if request.start_node_id not in node_types:
        raise WorkflowNodeInputError(f"unsupported start_node_id: {request.start_node_id}")
    start_index = node_types.index(request.start_node_id)
    if request.run_downstream:
        return node_types[start_index:]
    return [request.start_node_id]


def requirements_output(request: AdWorkflowGenerateRequest) -> dict[str, Any]:
    return {
        "product": request.product_name,
        "core_selling_point": request.core_selling_point or request.product_description,
        "target_audience": request.target_audience,
        "campaign_goal": request.campaign_goal,
        "desired_emotion": request.desired_emotion,
        "duration_seconds": request.duration_seconds,
        "visual_style": request.visual_style or "brand-aligned commercial style",
        "references": request.references,
        "selected_assets": selected_asset_summary(request.selected_assets),
    }


def product_design_output(
    request: AdWorkflowGenerateRequest,
    requirements: dict[str, Any],
) -> dict[str, Any]:
    selling_point = request.core_selling_point or request.product_description
    return {
        "showcase_focus": selling_point,
        "presentation_strategy": (
            f"Present {request.product_name} as a clear solution for {request.target_audience}."
        ),
        "channels": request.channels,
        "requirements": requirements,
    }


def creative_direction_output(
    request: AdWorkflowGenerateRequest,
    active: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "concept": f"Show how {request.product_name} helps {request.target_audience}.",
        "key_message": f"{request.product_name}: a practical answer to a real need.",
        "tone": request.desired_emotion,
        "channels": request.channels,
        "requirements": output(active, "requirements-analysis"),
        "product_design": output(active, "product-design"),
    }


def bgm_output(
    request: AdWorkflowGenerateRequest,
    active: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "music_style": "brand-safe commercial background music",
        "mood": request.desired_emotion,
        "tempo": "medium",
        "instruments": ["soft synth", "light percussion", "warm pad"],
        "structure": ["intro hook", "product showcase lift", "CTA resolution"],
        "start_time": "00:00:00,000",
        "end_time": f"00:00:{request.duration_seconds:02},000",
        "fade_in": "00:00:01,000",
        "fade_out": "00:00:02,000",
        "generation_prompt": (
            f"Generate {request.desired_emotion} background music for a "
            f"{request.duration_seconds}-second ad with no voices and no sound effects."
        ),
        "sync_notes": "Keep room for visuals and align lifts to visual transitions.",
    }
    return BgmOutput.model_validate(payload).model_dump()


def can_reuse_active_result(active_result: dict[str, Any], data_dir: Any = None) -> bool:
    if active_result.get("status") != "completed" or not active_result.get("output"):
        return False
    node_type = active_result.get("node_type") or active_result.get("node_id")
    node_output = active_result.get("output")
    if node_type == "final-composition" and isinstance(node_output, dict):
        local_path = node_output.get("local_path")
        if (
            node_output.get("status") != "ready"
            or not isinstance(local_path, str)
            or not local_path
        ):
            return False
        return data_dir is None or (data_dir / local_path).exists()
    return True


def should_force_selected_rerun(request: WorkflowRunRequest) -> bool:
    if request.mode == "force_rerun_all":
        return True
    return bool(request.force_rerun and request.start_node_id)


def fallback_run_is_no_op(
    selected_node_types: list[str],
    active: dict[str, dict[str, Any]],
    request: WorkflowRunRequest,
    data_dir: Any = None,
) -> bool:
    if request.mode != "run_from_frontier" or request.start_node_id is not None:
        return False
    if not selected_node_types:
        return True
    return all(
        can_reuse_active_result(active.get(node_type, {}), data_dir)
        for node_type in selected_node_types
    )


def fallback_no_op_response(
    *,
    workflow_id: str,
    execution_id: str,
    request: WorkflowRunRequest,
    skipped_nodes: list[str],
    media_status: Any,
) -> WorkflowRunResponse:
    return build_workflow_run_response(
        workflow_id=workflow_id,
        execution_id=execution_id,
        mode=request.mode,
        status="no_op",
        frontier_node_id="",
        executed_node_ids=[],
        skipped_node_ids=skipped_nodes,
        failed_node_id="",
        message="Workflow is already completed and has no stale nodes.",
        media_status=media_status.model_dump(mode="json"),
        final_video=media_status.final_video,
        affected_downstream_nodes=[],
    )


def fallback_frontier_node_id(
    request: WorkflowRunRequest,
    selected_node_types: list[str],
) -> str:
    if request.mode == "force_rerun_all":
        return selected_node_types[0] if selected_node_types else ""
    return request.target_node_id or request.start_node_id or ""


def effective_graph_run_mode(request: WorkflowRunRequest) -> str:
    if request.revision is not None or request.mode == "single_entity":
        return "single_entity"
    if request.mode == "force_rerun_all":
        return "force_rerun_all"
    if request.mode == "single_node" or (request.start_node_id and not request.run_downstream):
        return "single_node"
    return request.mode


def workflow_run_message(
    mode: str,
    frontier_node_id: str,
    failed_nodes: list[dict[str, str]],
) -> str:
    if failed_nodes:
        failed = failed_nodes[0]
        return f"Workflow run stopped at {failed['node_id']}: {failed['error']}"
    if mode == "run_from_frontier" and frontier_node_id:
        return f"Workflow run started from dirty frontier node {frontier_node_id}."
    if mode == "force_rerun_all":
        return "Workflow force rerun executed all graph nodes."
    if mode == "single_node" and frontier_node_id:
        return f"Workflow single node run executed {frontier_node_id}."
    return ""


def workflow_run_status(
    failed_nodes: list[dict[str, str]],
    waiting_nodes: list[str],
    *,
    failed_status: str = "partial_failed",
) -> str:
    if failed_nodes:
        return failed_status
    if waiting_nodes:
        return "waiting"
    return "completed"


def execution_status_from_run_status(status: str) -> str:
    if status == "no_op":
        return "completed"
    if status in {"completed", "waiting", "partial_failed", "failed", "cancelled"}:
        return status
    return "failed"


def result_error_message(result: dict[str, Any]) -> str:
    error = result.get("error")
    if error not in (None, ""):
        return str(error)
    node_output = result.get("output")
    if isinstance(node_output, dict) and node_output.get("error") not in (None, ""):
        return str(node_output["error"])
    return "Node execution failed."


def validate_ad_request_payload(
    workflow_id: str,
    raw_ad_request: Any,
    *,
    source: str,
) -> AdWorkflowGenerateRequest:
    if not isinstance(raw_ad_request, dict) or not raw_ad_request:
        raise WorkflowNodeInputError(
            "invalid_ad_request: workflow ad_request is missing for "
            f"{workflow_id}. Required fields include product_name, "
            "product_description, and target_audience."
        )
    try:
        return AdWorkflowGenerateRequest.model_validate(raw_ad_request)
    except ValidationError as exc:
        missing_fields = [
            ".".join(str(part) for part in error.get("loc", ()))
            for error in exc.errors()
            if error.get("type") == "missing"
        ]
        detail = (
            f"invalid_ad_request: {source} for {workflow_id} is missing required or valid fields."
        )
        if missing_fields:
            detail += f" Missing fields: {', '.join(missing_fields)}."
        detail += f" Validation error: {exc}"
        raise WorkflowNodeInputError(detail) from exc


def update_graph_node_from_result(node: WorkflowGraphNode, result: dict[str, Any]) -> None:
    _apply_run_result_to_graph_node(node, result)
