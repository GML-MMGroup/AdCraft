from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.schemas.workflow_nodes import (
    WorkflowRunRequest,
    WorkflowRunResponse,
)
from app.services.workflow_input_resolver import WorkflowNodeInputResolver
from app.services.workflow_run_response_builder import build_workflow_run_response
from app.services.workflow_run_plan_adapter import (
    fallback_frontier_node_id as _fallback_frontier_node_id,
    fallback_no_op_response as _fallback_no_op_response,
    fallback_run_is_no_op as _fallback_run_is_no_op,
    result_error_message as _result_error_message,
    should_force_selected_rerun as _should_force_selected_rerun,
    validate_ad_request_payload as _validate_ad_request_payload,
    workflow_run_message as _workflow_run_message,
    workflow_run_status as _workflow_run_status,
)
from app.services.workflow_run_utils import new_items as _new_items
from app.services.workflow_run_utils import (
    should_skip_node_results_only_node as _should_skip_node_results_only_node,
)


class WorkflowPlanRunExecutorMixin:
    def _run_saved_plan(
        self,
        workflow_id: str,
        request: WorkflowRunRequest,
        plan: dict[str, Any],
    ) -> WorkflowRunResponse:
        execution_id = f"exec_{uuid4().hex[:12]}"
        executed_nodes: list[str] = []
        skipped_nodes: list[str] = []
        stale_nodes: list[str] = []
        waiting_nodes: list[str] = []
        failed_nodes: list[dict[str, str]] = []
        affected_downstream_nodes: list[str] = []
        active = self._input_builder.load_active_results(workflow_id)
        ad_request = _validate_ad_request_payload(
            workflow_id,
            plan.get("ad_request"),
            source="workflow plan",
        )
        plan_node_types = [node["id"] for node in plan.get("workflow", {}).get("nodes", [])]
        selected_node_types = self._plan_adapter.selected_plan_node_types(plan_node_types, request)
        if _fallback_run_is_no_op(
            selected_node_types, active, request, self._settings.media_data_dir
        ):
            media_status = self._media_tasks.media_status(workflow_id)
            return _fallback_no_op_response(
                workflow_id=workflow_id,
                execution_id=execution_id,
                request=request,
                skipped_nodes=selected_node_types,
                media_status=media_status,
            )
        force_selected = _should_force_selected_rerun(request)

        for node_type in selected_node_types:
            active_result = active.get(node_type)
            if _should_skip_node_results_only_node(
                active_result,
                force_selected=force_selected,
                data_dir=self._settings.media_data_dir,
            ):
                skipped_nodes.append(node_type)
                continue
            try:
                result = self._execute_planned_node(
                    workflow_id=workflow_id,
                    node_type=node_type,
                    ad_request=ad_request,
                    request=request,
                    active=active,
                )
                if result.get("status") == "failed":
                    failed_nodes.append(
                        {"node_id": node_type, "error": _result_error_message(result)}
                    )
                    break
                active[node_type] = result
                executed_nodes.append(node_type)
                if result.get("status") == "waiting":
                    waiting_nodes.append(node_type)
                    if node_type not in stale_nodes:
                        stale_nodes.append(node_type)
                affected_downstream_nodes.extend(
                    _new_items(
                        affected_downstream_nodes,
                        WorkflowNodeInputResolver(self._settings).update_downstream_resolved_inputs(
                            workflow_id, node_type
                        ),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - API returns per-node failure details.
                failed_nodes.append({"node_id": node_type, "error": str(exc)})
                if not request.run_downstream:
                    break

        media_status = self._post_run_media_status(workflow_id, request)
        status = _workflow_run_status(failed_nodes, waiting_nodes)
        frontier_node_id = _fallback_frontier_node_id(request, selected_node_types)
        return build_workflow_run_response(
            workflow_id=workflow_id,
            execution_id=execution_id,
            mode=request.mode,
            status=status,
            frontier_node_id=frontier_node_id,
            executed_node_ids=executed_nodes,
            skipped_node_ids=skipped_nodes,
            waiting_node_ids=stale_nodes,
            failed_node_id=failed_nodes[0]["node_id"] if failed_nodes else "",
            message=_workflow_run_message(request.mode, frontier_node_id, failed_nodes),
            failed_node_errors=failed_nodes,
            media_status=media_status.model_dump(mode="json"),
            final_video=media_status.final_video,
            affected_downstream_nodes=affected_downstream_nodes,
        )
