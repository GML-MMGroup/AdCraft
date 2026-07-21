from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.schemas.ad_workflow import AdWorkflowGenerateRequest
from app.schemas.workflow_nodes import (
    WorkflowNodeRunRequest,
    WorkflowRunRequest,
    WorkflowRunResponse,
)
from app.services.workflow_graph import (
    WorkflowGraph,
    WorkflowGraphNode,
    load_graph,
    save_graph,
    topological_node_ids,
)
from app.services.workflow_executions import (
    TERMINAL_EXECUTION_STATUSES,
    WorkflowExecutionService,
)
from app.services.media_tasks import MediaTaskService
from app.services.workflow_nodes import (
    WorkflowNodeExecutionService,
    WorkflowNodeInputError,
)
from app.services.workflow_run_inputs import (
    WorkflowRunInputBuilder,
    graph_node_as_active_result as _graph_node_as_active_result,
)
from app.services.workflow_run_events import WorkflowRunEventRecorder
from app.services.workflow_run_response_builder import build_workflow_run_response
from app.services.workflow_run_plan_adapter import (
    WorkflowRunPlanAdapter,
    can_reuse_active_result as _can_reuse_active_result,
    effective_graph_run_mode as _effective_graph_run_mode,
    execution_status_from_run_status as _execution_status_from_run_status,
    fallback_frontier_node_id as _fallback_frontier_node_id,
    result_error_message as _result_error_message,
    workflow_run_message as _workflow_run_message,
    workflow_run_status as _workflow_run_status,
)
from app.services.workflow_run_scheduler import (
    required_downstream_by_node as _required_downstream_by_node,
    required_upstreams_by_node as _required_upstreams_by_node,
    select_graph_run_node_ids as _select_graph_run_node_ids,
)
from app.services.workflow_state import (
    load_workflow_plan,
)

from app.services.workflow_graph_run_state import _GraphRunState
from app.services.workflow_node_results_runner import WorkflowNodeResultsRunnerMixin
from app.services.workflow_parallel_graph_runner import WorkflowParallelGraphRunnerMixin
from app.services.workflow_plan_run_executor import WorkflowPlanRunExecutorMixin
from app.services.workflow_run_media_finalizer import WorkflowRunMediaFinalizerMixin
from app.services.workflow_run_utils import order_node_subset as _order_node_subset
from app.services.workflow_run_utils import utc_now_iso


class WorkflowCanvasExecutionService(
    WorkflowParallelGraphRunnerMixin,
    WorkflowPlanRunExecutorMixin,
    WorkflowNodeResultsRunnerMixin,
    WorkflowRunMediaFinalizerMixin,
):
    def __init__(self, settings: Settings) -> None:
        from app.services.canvas_runtime_events import CanvasRuntimeRecoveryService

        self._settings = settings
        self._node_service = WorkflowNodeExecutionService(settings)
        self._media_tasks = MediaTaskService(settings)
        self._executions = WorkflowExecutionService(settings.media_data_dir)
        self._event_recorder = WorkflowRunEventRecorder(self._executions)
        self._input_builder = WorkflowRunInputBuilder(settings)
        self._plan_adapter = WorkflowRunPlanAdapter(settings)
        self._runtime_recovery = CanvasRuntimeRecoveryService(settings)

    def run(self, workflow_id: str, request: WorkflowRunRequest) -> WorkflowRunResponse:
        if request.mode == "single_entity" or request.revision is not None:
            return self._run_single_entity(workflow_id, request)
        graph = load_graph(self._settings.media_data_dir, workflow_id)
        if graph is not None:
            return self._run_saved_graph(workflow_id, request, graph)
        plan = load_workflow_plan(self._settings.media_data_dir, workflow_id)
        if plan is not None:
            return self._run_saved_plan(workflow_id, request, plan)
        return self._run_node_results_only(workflow_id, request)

    def start_execution(
        self,
        workflow_id: str,
        request: WorkflowRunRequest,
    ):
        self._runtime_recovery.recover_workflow_runtime(workflow_id)
        if request.mode == "single_entity" or request.revision is not None:
            node_id = request.target_node_id or request.start_node_id
            if not node_id:
                raise WorkflowNodeInputError("single_entity run requires target_node_id.")
            return self._executions.create_execution(
                workflow_id,
                request,
                selected_node_ids=[node_id],
                frontier_node_id=node_id,
                graph_nodes=[{"id": node_id, "node_type": node_id}],
                mode="single_entity",
            )

        graph = load_graph(self._settings.media_data_dir, workflow_id)
        if graph is not None:
            active = self._input_builder.load_active_results(workflow_id)
            self._plan_adapter.ad_request_from_graph_or_plan(workflow_id, graph)
            graph_nodes = {node.id: node for node in graph.nodes}
            mode = _effective_graph_run_mode(request)
            ordered_node_ids = topological_node_ids(graph)
            node_ids, frontier_node_id, _report_skipped_nodes = _select_graph_run_node_ids(
                graph=graph,
                request=request,
                active=active,
                graph_nodes=graph_nodes,
                ordered_node_ids=ordered_node_ids,
                mode=mode,
            )
            return self._executions.create_execution(
                workflow_id,
                request,
                selected_node_ids=node_ids,
                frontier_node_id=frontier_node_id,
                graph_nodes=graph.nodes,
                mode=mode,
            )

        selected_node_types = self._plan_adapter.selected_node_types(request)
        frontier_node_id = _fallback_frontier_node_id(request, selected_node_types)
        mode = _effective_graph_run_mode(request)
        return self._executions.create_execution(
            workflow_id,
            request,
            selected_node_ids=selected_node_types,
            frontier_node_id=frontier_node_id,
            graph_nodes=[{"id": node_id, "node_type": node_id} for node_id in selected_node_types],
            mode=mode,
        )

    def run_execution(self, workflow_id: str, execution_id: str) -> None:
        state = self._executions.load_execution(workflow_id, execution_id)
        if state.status in TERMINAL_EXECUTION_STATUSES:
            return
        request = WorkflowRunRequest.model_validate(state.request or {})
        self._executions.update_execution(
            workflow_id,
            execution_id,
            status="running",
            started_at=utc_now_iso(),
        )
        self._executions.append_event(
            workflow_id,
            execution_id,
            "execution_started",
            payload={"mode": state.mode},
        )
        try:
            if request.mode == "single_entity" or request.revision is not None:
                node_id = request.target_node_id or request.start_node_id or state.frontier_node_id
                self._event_recorder.record_node_started(workflow_id, execution_id, node_id)
                result = self._run_single_entity(
                    workflow_id,
                    request,
                    execution_id=execution_id,
                )
                result_payload = result.model_dump(mode="json")
                if result.status == "failed":
                    self._event_recorder.record_node_failed(
                        workflow_id,
                        execution_id,
                        node_id,
                        error=result.error or _result_error_message(result_payload),
                        result=result_payload,
                    )
                elif result.status == "waiting":
                    self._event_recorder.record_node_waiting(
                        workflow_id,
                        execution_id,
                        node_id,
                        result=result_payload,
                    )
                elif result.status == "skipped":
                    self._event_recorder.record_node_skipped(
                        workflow_id,
                        execution_id,
                        node_id,
                        reason="node_service_skipped",
                        result=result_payload,
                    )
                else:
                    self._event_recorder.record_node_completed(
                        workflow_id,
                        execution_id,
                        node_id,
                        result=result_payload,
                    )
            else:
                graph = load_graph(self._settings.media_data_dir, workflow_id)
                if graph is not None:
                    result = self._run_saved_graph(
                        workflow_id,
                        request,
                        graph,
                        execution_id=execution_id,
                    )
                else:
                    result = self._run_node_results_only(
                        workflow_id,
                        request,
                        execution_id=execution_id,
                    )
            final_status = _execution_status_from_run_status(result.status)
            self._executions.finish_execution(
                workflow_id,
                execution_id,
                final_status,
                final_result=result.model_dump(mode="json"),
                error=result.message if final_status in {"failed", "partial_failed"} else None,
            )
            if final_status in TERMINAL_EXECUTION_STATUSES or final_status == "waiting":
                self._executions.clear_active_execution(workflow_id, execution_id)
        except Exception as exc:  # noqa: BLE001 - scheduler failure is persisted for polling clients.
            self._executions.finish_execution(
                workflow_id,
                execution_id,
                "failed",
                error=str(exc),
            )
            self._executions.clear_active_execution(workflow_id, execution_id)

    def get_execution(self, workflow_id: str, execution_id: str):
        return self._executions.load_execution(workflow_id, execution_id)

    def list_execution_events(
        self,
        workflow_id: str,
        execution_id: str,
        *,
        after_seq: int = 0,
    ):
        return self._executions.list_events(
            workflow_id,
            execution_id,
            after_seq=after_seq,
        )

    def _run_single_entity(
        self,
        workflow_id: str,
        request: WorkflowRunRequest,
        *,
        execution_id: str | None = None,
    ) -> WorkflowRunResponse:
        if request.revision is None:
            raise WorkflowNodeInputError("single_entity run requires revision.")
        node_id = request.target_node_id or request.start_node_id
        if not node_id:
            raise WorkflowNodeInputError("single_entity run requires target_node_id.")
        response_execution_id = execution_id or f"exec_{uuid4().hex[:12]}"
        result = self._node_service.run(
            WorkflowNodeRunRequest(
                workflow_id=workflow_id,
                node_type=node_id,
                mode="mock" if self._settings.agno_mock_mode else "real",
                media_mode=self._settings.media_mode,
                force_rerun=True,
                revision=request.revision,
                asset_references=request.asset_references,
                library_entity_ids=request.library_entity_ids,
                reference_mode=request.reference_mode,
                provider=request.provider,
                allow_provider_fallback=request.allow_provider_fallback,
                provider_hints=request.provider_hints,
            )
        )
        graph = load_graph(self._settings.media_data_dir, workflow_id)
        media_status = self._media_tasks.media_status(workflow_id)
        failed_nodes = (
            [{"node_id": node_id, "error": result.error or "single_entity revision failed"}]
            if result.status == "failed"
            else []
        )
        waiting_nodes = [node_id] if result.status == "waiting" else []
        return build_workflow_run_response(
            workflow_id=workflow_id,
            execution_id=response_execution_id,
            mode="single_entity",
            status=_workflow_run_status(failed_nodes, waiting_nodes, failed_status="failed"),
            frontier_node_id=node_id,
            executed_node_ids=[] if failed_nodes else [node_id],
            skipped_node_ids=[],
            waiting_node_ids=waiting_nodes,
            failed_node_id=node_id if failed_nodes else "",
            message=_workflow_run_message("single_node", node_id, failed_nodes),
            graph=graph.model_dump(mode="json") if graph else {},
            failed_node_errors=failed_nodes,
            media_status=media_status.model_dump(mode="json"),
            final_video=media_status.final_video,
            affected_downstream_nodes=result.affected_downstream_nodes,
        )

    def _run_saved_graph(
        self,
        workflow_id: str,
        request: WorkflowRunRequest,
        graph: WorkflowGraph,
        *,
        execution_id: str | None = None,
    ) -> WorkflowRunResponse:
        response_execution_id = execution_id or f"exec_{uuid4().hex[:12]}"
        executed_nodes: list[str] = []
        skipped_nodes: list[str] = []
        stale_nodes: list[str] = []
        failed_nodes: list[dict[str, str]] = []
        active = self._input_builder.load_active_results(workflow_id)
        ad_request = self._plan_adapter.ad_request_from_graph_or_plan(workflow_id, graph)
        graph_nodes = {node.id: node for node in graph.nodes}
        mode = _effective_graph_run_mode(request)

        try:
            ordered_node_ids = topological_node_ids(graph)
            node_ids, frontier_node_id, report_skipped_nodes = _select_graph_run_node_ids(
                graph=graph,
                request=request,
                active=active,
                graph_nodes=graph_nodes,
                ordered_node_ids=ordered_node_ids,
                mode=mode,
            )
        except Exception as exc:  # noqa: BLE001 - API reports graph selection errors.
            failed_nodes.append(
                {
                    "node_id": request.target_node_id or request.start_node_id or "workflow",
                    "error": str(exc),
                }
            )
            media_status = self._post_run_media_status(workflow_id, request)
            return build_workflow_run_response(
                workflow_id=workflow_id,
                execution_id=response_execution_id,
                mode=mode,
                status="partial_failed",
                failed_node_id=failed_nodes[0]["node_id"],
                executed_node_ids=executed_nodes,
                skipped_node_ids=skipped_nodes,
                waiting_node_ids=stale_nodes,
                failed_node_errors=failed_nodes,
                media_status=media_status.model_dump(mode="json"),
                final_video=media_status.final_video,
                graph=graph.model_dump(mode="json"),
            )

        if mode == "run_from_frontier" and not node_ids:
            media_status = self._media_tasks.media_status(workflow_id)
            return build_workflow_run_response(
                workflow_id=workflow_id,
                execution_id=response_execution_id,
                mode=mode,
                status="no_op",
                frontier_node_id="",
                executed_node_ids=[],
                skipped_node_ids=ordered_node_ids,
                media_status=media_status.model_dump(mode="json"),
                final_video=media_status.final_video,
                affected_downstream_nodes=[],
                message="Workflow is already completed and has no stale nodes.",
                graph=graph.model_dump(mode="json"),
            )

        return self._run_saved_graph_parallel(
            workflow_id=workflow_id,
            request=request,
            graph=graph,
            response_execution_id=response_execution_id,
            active=active,
            ad_request=ad_request,
            graph_nodes=graph_nodes,
            ordered_node_ids=ordered_node_ids,
            node_ids=node_ids,
            frontier_node_id=frontier_node_id,
            report_skipped_nodes=report_skipped_nodes,
            mode=mode,
        )

    def _run_saved_graph_parallel(
        self,
        *,
        workflow_id: str,
        request: WorkflowRunRequest,
        graph: WorkflowGraph,
        response_execution_id: str,
        active: dict[str, dict[str, Any]],
        ad_request: AdWorkflowGenerateRequest,
        graph_nodes: dict[str, WorkflowGraphNode],
        ordered_node_ids: list[str],
        node_ids: list[str],
        frontier_node_id: str,
        report_skipped_nodes: bool,
        mode: str,
    ) -> WorkflowRunResponse:
        state = _GraphRunState(selected=set(node_ids))
        loop_node_ids = ordered_node_ids if report_skipped_nodes else node_ids
        allow_reuse_for_selected = not (
            mode == "force_rerun_all"
            or (mode == "run_from_frontier" and request.start_node_id is None)
        )
        graph.status = "running"
        graph = save_graph(self._settings.media_data_dir, graph)
        self._prepare_graph_execution_skips(
            workflow_id=workflow_id,
            execution_id=response_execution_id,
            loop_node_ids=loop_node_ids,
            request=request,
            graph_nodes=graph_nodes,
            active=active,
            allow_reuse_for_selected=allow_reuse_for_selected,
            state=state,
        )

        required_upstreams = _required_upstreams_by_node(graph)
        required_downstream = _required_downstream_by_node(graph)
        if mode == "single_node":
            required_upstreams = {node_id: [] for node_id in required_upstreams}
            required_downstream = {node_id: [] for node_id in required_downstream}
        graph = self._run_graph_scheduler_loop(
            workflow_id=workflow_id,
            execution_id=response_execution_id,
            graph=graph,
            request=request,
            ad_request=ad_request,
            graph_nodes=graph_nodes,
            node_ids=node_ids,
            active=active,
            required_upstreams=required_upstreams,
            required_downstream=required_downstream,
            state=state,
        )

        if state.failed_nodes or state.blocked_nodes:
            graph.status = "failed"
        else:
            graph.status = "running" if state.waiting_nodes else "completed"
        graph = save_graph(self._settings.media_data_dir, graph)
        media_status = self._post_run_media_status(workflow_id, request)
        status = (
            "partial_failed"
            if state.failed_nodes or state.blocked_nodes
            else _workflow_run_status(state.failed_nodes, state.waiting_nodes)
        )
        ordered_executed_nodes = _order_node_subset(node_ids, state.executed_nodes)
        ordered_completed_nodes = _order_node_subset(node_ids, state.completed_nodes)
        ordered_skipped_nodes = _order_node_subset(loop_node_ids, state.skipped_nodes)
        ordered_waiting_nodes = _order_node_subset(node_ids, state.waiting_nodes)
        return build_workflow_run_response(
            workflow_id=workflow_id,
            execution_id=response_execution_id,
            mode=mode,
            status=status,
            frontier_node_id=frontier_node_id,
            selected_node_ids=node_ids,
            completed_node_ids=ordered_completed_nodes,
            waiting_node_ids=ordered_waiting_nodes,
            failed_node_ids=[node["node_id"] for node in state.failed_nodes],
            executed_node_ids=ordered_executed_nodes,
            skipped_node_ids=ordered_skipped_nodes,
            failed_node_id=state.failed_nodes[0]["node_id"] if state.failed_nodes else "",
            message=_workflow_run_message(mode, frontier_node_id, state.failed_nodes),
            graph=graph.model_dump(mode="json"),
            failed_node_errors=state.failed_nodes,
            media_status=media_status.model_dump(mode="json"),
            final_video=media_status.final_video,
            affected_downstream_nodes=state.affected_downstream_nodes,
        )

    def _prepare_graph_execution_skips(
        self,
        *,
        workflow_id: str,
        execution_id: str | None,
        loop_node_ids: list[str],
        request: WorkflowRunRequest,
        graph_nodes: dict[str, WorkflowGraphNode],
        active: dict[str, dict[str, Any]],
        allow_reuse_for_selected: bool,
        state: _GraphRunState,
    ) -> None:
        for node_id in loop_node_ids:
            graph_node = graph_nodes[node_id]
            active_result = active.get(node_id)
            if graph_node.stale and node_id in state.selected:
                state.stale_nodes.append(node_id)
            reason = self._graph_pre_skip_reason(
                node_id=node_id,
                request=request,
                graph_node=graph_node,
                active_result=active_result,
                allow_reuse_for_selected=allow_reuse_for_selected,
                selected=state.selected,
            )
            if reason is None:
                continue
            if reason == "reused_graph_output":
                active[node_id] = _graph_node_as_active_result(graph_node)
                active_result = active[node_id]
            self._skip_graph_execution_node(
                workflow_id,
                execution_id,
                node_id,
                reason=reason,
                graph_node=graph_node,
                active=active,
                active_result=active_result,
                skipped=state.skipped,
                skipped_nodes=state.skipped_nodes,
                skipped_reasons=state.skipped_reasons,
            )

    def _graph_pre_skip_reason(
        self,
        *,
        node_id: str,
        request: WorkflowRunRequest,
        graph_node: WorkflowGraphNode,
        active_result: dict[str, Any] | None,
        allow_reuse_for_selected: bool,
        selected: set[str],
    ) -> str | None:
        if node_id not in selected:
            return "not_selected"
        if graph_node.locked and (active_result or graph_node.output):
            return "locked"
        if self._can_reuse_graph_output_before_run(
            request=request,
            graph_node=graph_node,
            active_result=active_result,
            allow_reuse_for_selected=allow_reuse_for_selected,
        ):
            return "reused_graph_output"
        if self._can_reuse_active_output_before_run(
            request=request,
            graph_node=graph_node,
            active_result=active_result,
            allow_reuse_for_selected=allow_reuse_for_selected,
        ):
            return "reused_active_output"
        if graph_node.category == "utility":
            return "utility_node"
        return None

    def _can_reuse_graph_output_before_run(
        self,
        *,
        request: WorkflowRunRequest,
        graph_node: WorkflowGraphNode,
        active_result: dict[str, Any] | None,
        allow_reuse_for_selected: bool,
    ) -> bool:
        return bool(
            allow_reuse_for_selected
            and request.only_missing
            and not active_result
            and graph_node.output
            and graph_node.status == "completed"
            and not graph_node.stale
            and not request.force_rerun
        )

    def _can_reuse_active_output_before_run(
        self,
        *,
        request: WorkflowRunRequest,
        graph_node: WorkflowGraphNode,
        active_result: dict[str, Any] | None,
        allow_reuse_for_selected: bool,
    ) -> bool:
        return bool(
            allow_reuse_for_selected
            and request.only_missing
            and active_result
            and _can_reuse_active_result(active_result, self._settings.media_data_dir)
            and not graph_node.stale
            and not request.force_rerun
        )
