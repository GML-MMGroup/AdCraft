from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.schemas.ad_workflow import AdWorkflowGenerateRequest
from app.schemas.workflow_nodes import (
    WorkflowRunRequest,
    WorkflowRunResponse,
)
from app.services.agent_trace import AgentTraceWriter
from app.services.workflow_graph import (
    WorkflowGraph,
    WorkflowGraphNode,
)
from app.services.workflow_run_inputs import (
    output as _output,
)
from app.services.workflow_run_response_builder import build_workflow_run_response
from app.services.workflow_run_plan_adapter import (
    fallback_frontier_node_id as _fallback_frontier_node_id,
    fallback_no_op_response as _fallback_no_op_response,
    fallback_run_is_no_op as _fallback_run_is_no_op,
    result_error_message as _result_error_message,
    should_force_selected_rerun as _should_force_selected_rerun,
    workflow_run_message as _workflow_run_message,
    workflow_run_status as _workflow_run_status,
)
from app.services.workflow_state import (
    persist_node_run,
)
from app.services.workflow_run_utils import new_items as _new_items
from app.services.workflow_run_utils import (
    should_skip_node_results_only_node as _should_skip_node_results_only_node,
)
from app.skills.registry import CORE_AGENT_BY_NODE, record_skill_trace


class WorkflowNodeResultsRunnerMixin:
    def _run_node_results_only(
        self,
        workflow_id: str,
        request: WorkflowRunRequest,
        *,
        execution_id: str | None = None,
    ) -> WorkflowRunResponse:
        response_execution_id = execution_id or f"exec_{uuid4().hex[:12]}"
        executed_nodes: list[str] = []
        skipped_nodes: list[str] = []
        stale_nodes: list[str] = []
        waiting_nodes: list[str] = []
        failed_nodes: list[dict[str, str]] = []
        affected_downstream_nodes: list[str] = []
        active = self._input_builder.load_active_results(workflow_id)
        selected_node_types = self._plan_adapter.selected_node_types(request)
        if _fallback_run_is_no_op(
            selected_node_types, active, request, self._settings.media_data_dir
        ):
            media_status = self._media_tasks.media_status(workflow_id)
            return _fallback_no_op_response(
                workflow_id=workflow_id,
                execution_id=response_execution_id,
                request=request,
                skipped_nodes=selected_node_types,
                media_status=media_status,
            )
        force_selected = _should_force_selected_rerun(request)

        for node_type in selected_node_types:
            outcome = self._run_node_results_only_node(
                workflow_id=workflow_id,
                execution_id=execution_id,
                node_type=node_type,
                request=request,
                active=active,
                force_selected=force_selected,
            )
            if outcome["status"] == "failed":
                failed_nodes.append({"node_id": node_type, "error": str(outcome["error"])})
                if not request.run_downstream:
                    break
                continue
            if outcome["status"] == "skipped":
                skipped_nodes.append(node_type)
                continue

            executed_nodes.append(node_type)
            if outcome["status"] == "waiting":
                waiting_nodes.append(node_type)
                if node_type not in stale_nodes:
                    stale_nodes.append(node_type)
            result_payload = outcome.get("result")
            if isinstance(result_payload, dict):
                active[node_type] = result_payload
            affected_downstream_nodes.extend(
                _new_items(
                    affected_downstream_nodes,
                    outcome.get("affected_downstream_nodes", []),
                )
            )

        media_status = self._post_run_media_status(workflow_id, request)
        status = _workflow_run_status(failed_nodes, waiting_nodes)
        frontier_node_id = _fallback_frontier_node_id(request, selected_node_types)
        return build_workflow_run_response(
            workflow_id=workflow_id,
            execution_id=response_execution_id,
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

    def _run_node_results_only_node(
        self,
        *,
        workflow_id: str,
        execution_id: str | None,
        node_type: str,
        request: WorkflowRunRequest,
        active: dict[str, dict[str, Any]],
        force_selected: bool,
    ) -> dict[str, Any]:
        active_result = active.get(node_type)
        if _should_skip_node_results_only_node(
            active_result,
            force_selected=force_selected,
            data_dir=self._settings.media_data_dir,
        ):
            self._event_recorder.record_node_skipped(
                workflow_id,
                execution_id,
                node_type,
                reason="reused_active_output",
            )
            return {"status": "skipped"}

        try:
            self._event_recorder.record_node_started(workflow_id, execution_id, node_type)
            node_request = self._input_builder.build_node_request(
                workflow_id,
                node_type,
                request,
                active,
            )
            result = self._node_service.run(node_request)
            result_payload = result.model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001 - API needs per-node failure details.
            self._event_recorder.record_node_failed(
                workflow_id,
                execution_id,
                node_type,
                error=str(exc),
            )
            return {"status": "failed", "error": str(exc)}

        if result.status == "failed":
            error = result.error or _result_error_message(result_payload)
            self._event_recorder.record_node_failed(
                workflow_id,
                execution_id,
                node_type,
                error=error,
                result=result_payload,
            )
            return {"status": "failed", "error": error}
        if result.status == "skipped":
            self._event_recorder.record_node_skipped(
                workflow_id,
                execution_id,
                node_type,
                reason="node_service_skipped",
                result=result_payload,
            )
            return {
                "status": "skipped",
                "result": result_payload,
                "affected_downstream_nodes": result.affected_downstream_nodes,
            }
        if result.status == "waiting":
            self._event_recorder.record_node_waiting(
                workflow_id,
                execution_id,
                node_type,
                result=result_payload,
            )
        elif result.status == "completed":
            self._event_recorder.record_node_completed(
                workflow_id,
                execution_id,
                node_type,
                result=result_payload,
            )
        return {
            "status": result.status,
            "result": result_payload,
            "affected_downstream_nodes": result.affected_downstream_nodes,
        }

    def _execute_planned_node(
        self,
        *,
        workflow_id: str,
        node_type: str,
        ad_request: AdWorkflowGenerateRequest,
        request: WorkflowRunRequest,
        active: dict[str, dict[str, Any]],
        graph_node: WorkflowGraphNode | None = None,
        graph: WorkflowGraph | None = None,
    ) -> dict[str, Any]:
        if node_type == "requirements-analysis":
            return self._persist_direct_node(
                workflow_id,
                node_type,
                self._plan_adapter.requirements_output(ad_request),
                {},
            )
        if node_type == "product-design":
            return self._persist_direct_node(
                workflow_id,
                node_type,
                self._plan_adapter.product_design_output(
                    ad_request,
                    _output(active, "requirements-analysis"),
                ),
                {"requirements": _output(active, "requirements-analysis")},
            )
        if node_type == "creative-direction":
            return self._persist_direct_node(
                workflow_id,
                node_type,
                self._plan_adapter.creative_direction_output(ad_request, active),
                {
                    "requirements": _output(active, "requirements-analysis"),
                    "product_design": _output(active, "product-design"),
                },
            )
        if node_type == "bgm" and graph is None:
            return self._persist_direct_node(
                workflow_id,
                node_type,
                self._plan_adapter.bgm_output(ad_request, active),
                {
                    "requirements": _output(active, "requirements-analysis"),
                    "creative_direction": _output(active, "creative-direction"),
                    "script": _output(active, "script"),
                },
            )

        if graph is not None and graph_node is not None:
            node_request = self._input_builder.build_graph_node_request(
                workflow_id=workflow_id,
                node_type=node_type,
                request=request,
                graph_node=graph_node,
            )
        else:
            node_request = self._input_builder.build_planned_node_request(
                workflow_id=workflow_id,
                node_type=node_type,
                request=request,
                active=active,
                ad_request=ad_request,
                graph_node=graph_node,
            )
        result = self._node_service.run(node_request)
        return result.model_dump(mode="json")

    def _persist_direct_node(
        self,
        workflow_id: str,
        node_type: str,
        output: dict[str, Any],
        input_context: dict[str, Any],
    ) -> dict[str, Any]:
        trace_writer = AgentTraceWriter(self._settings.media_data_dir, workflow_id)
        record_skill_trace(
            node_id=node_type,
            core_agent_name=CORE_AGENT_BY_NODE.get(
                node_type,
                node_type,
            ),
            context={**input_context, "draft_output": output},
            trace_writer=trace_writer,
            mock_mode=True,
        )
        return persist_node_run(
            workflow_id=workflow_id,
            node_id=node_type,
            node_type=node_type,
            status="completed",
            output=output,
            input_assets=[],
            output_assets=[],
            input_context=input_context,
            error=None,
            source="workflows/run",
            data_dir=self._settings.media_data_dir,
        )
