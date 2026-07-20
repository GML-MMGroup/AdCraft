from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any

from app.schemas.ad_workflow import AdWorkflowGenerateRequest
from app.schemas.workflow_nodes import (
    WorkflowRunRequest,
)
from app.services.workflow_graph import (
    WorkflowGraph,
    WorkflowGraphNode,
    save_graph,
)
from app.services.workflow_input_resolver import WorkflowNodeInputResolver
from app.services.workflow_nodes import (
    WorkflowNodeExecutionError,
    WorkflowNodeInputError,
)
from app.services.workflow_run_inputs import (
    graph_node_as_active_result as _graph_node_as_active_result,
)
from app.services.workflow_run_plan_adapter import (
    result_error_message as _result_error_message,
    update_graph_node_from_result as _update_graph_node_from_result,
)
from app.services.workflow_run_scheduler import (
    ParallelNodeOutcome as _ParallelNodeOutcome,
    failed_graph_result_for_scheduler as _failed_graph_result_for_scheduler,
    future_outcome as _future_outcome,
    next_ready_node_id as _next_ready_node_id,
    required_reachable_downstream as _required_reachable_downstream,
    unsatisfied_upstream_node_ids as _unsatisfied_upstream_node_ids,
)
from app.services.workflow_run_utils import new_items as _new_items

from app.services.workflow_graph_run_state import _GraphRunState


class WorkflowParallelGraphRunnerMixin:
    def _run_graph_scheduler_loop(
        self,
        *,
        workflow_id: str,
        execution_id: str,
        graph: WorkflowGraph,
        request: WorkflowRunRequest,
        ad_request: AdWorkflowGenerateRequest,
        graph_nodes: dict[str, WorkflowGraphNode],
        node_ids: list[str],
        active: dict[str, dict[str, Any]],
        required_upstreams: dict[str, list[str]],
        required_downstream: dict[str, list[str]],
        state: _GraphRunState,
    ) -> WorkflowGraph:
        max_workers = self._workflow_max_workers()
        futures: dict[Future[_ParallelNodeOutcome], str] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            while True:
                self._submit_ready_graph_nodes(
                    executor=executor,
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    graph=graph,
                    request=request,
                    ad_request=ad_request,
                    graph_nodes=graph_nodes,
                    node_ids=node_ids,
                    active=active,
                    required_upstreams=required_upstreams,
                    futures=futures,
                    state=state,
                )
                if futures:
                    graph = self._drain_completed_graph_futures(
                        workflow_id=workflow_id,
                        execution_id=execution_id,
                        graph=graph,
                        graph_nodes=graph_nodes,
                        active=active,
                        required_downstream=required_downstream,
                        futures=futures,
                        state=state,
                    )
                    continue
                if self._graph_scheduler_should_stop(state):
                    break
                if self._block_unsatisfied_graph_scheduler_nodes(
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    active=active,
                    graph_nodes=graph_nodes,
                    required_upstreams=required_upstreams,
                    state=state,
                ):
                    graph = save_graph(self._settings.media_data_dir, graph)
                    continue
                break
        return graph

    def _workflow_max_workers(self) -> int:
        if not self._settings.workflow_parallel_scheduler_enabled:
            return 1
        return max(1, int(self._settings.workflow_max_parallel_nodes or 1))

    def _submit_ready_graph_nodes(
        self,
        *,
        executor: ThreadPoolExecutor,
        workflow_id: str,
        execution_id: str,
        graph: WorkflowGraph,
        request: WorkflowRunRequest,
        ad_request: AdWorkflowGenerateRequest,
        graph_nodes: dict[str, WorkflowGraphNode],
        node_ids: list[str],
        active: dict[str, dict[str, Any]],
        required_upstreams: dict[str, list[str]],
        futures: dict[Future[_ParallelNodeOutcome], str],
        state: _GraphRunState,
    ) -> None:
        while len(futures) < self._workflow_max_workers():
            ready_node_id = _next_ready_node_id(
                node_ids,
                selected=state.selected,
                completed=state.completed,
                failed=state.failed,
                waiting=state.waiting,
                skipped=state.skipped,
                blocked=state.blocked,
                running=state.running_node_ids,
                required_upstreams=required_upstreams,
                skipped_reasons=state.skipped_reasons,
                active=active,
                graph_nodes=graph_nodes,
                data_dir=self._settings.media_data_dir,
            )
            if ready_node_id is None:
                break
            graph_node = graph_nodes[ready_node_id]
            state.running_node_ids.add(ready_node_id)
            self._event_recorder.record_node_started(workflow_id, execution_id, ready_node_id)
            futures[
                executor.submit(
                    self._execute_parallel_graph_node,
                    workflow_id=workflow_id,
                    node_id=ready_node_id,
                    node_type=graph_node.node_type,
                    ad_request=ad_request,
                    request=request,
                    active=dict(active),
                    graph_node=graph_node,
                    graph=graph,
                )
            ] = ready_node_id

    def _drain_completed_graph_futures(
        self,
        *,
        workflow_id: str,
        execution_id: str,
        graph: WorkflowGraph,
        graph_nodes: dict[str, WorkflowGraphNode],
        active: dict[str, dict[str, Any]],
        required_downstream: dict[str, list[str]],
        futures: dict[Future[_ParallelNodeOutcome], str],
        state: _GraphRunState,
    ) -> WorkflowGraph:
        done, _pending = wait(futures.keys(), return_when=FIRST_COMPLETED)
        for future in done:
            node_id = futures.pop(future)
            state.running_node_ids.discard(node_id)
            graph_node = graph_nodes[node_id]
            outcome = _future_outcome(future, node_id, graph_node.node_type)
            self._apply_graph_node_outcome(
                workflow_id=workflow_id,
                execution_id=execution_id,
                node_id=node_id,
                graph_node=graph_node,
                outcome=outcome,
                active=active,
                required_downstream=required_downstream,
                graph_nodes=graph_nodes,
                state=state,
            )
            graph = save_graph(self._settings.media_data_dir, graph)
        return graph

    def _apply_graph_node_outcome(
        self,
        *,
        workflow_id: str,
        execution_id: str,
        node_id: str,
        graph_node: WorkflowGraphNode,
        outcome: _ParallelNodeOutcome,
        active: dict[str, dict[str, Any]],
        required_downstream: dict[str, list[str]],
        graph_nodes: dict[str, WorkflowGraphNode],
        state: _GraphRunState,
    ) -> None:
        result = outcome.result
        if outcome.error or result is None or result.get("status") == "failed":
            self._apply_failed_graph_node_outcome(
                workflow_id=workflow_id,
                execution_id=execution_id,
                node_id=node_id,
                graph_node=graph_node,
                result=result,
                error=outcome.error or _result_error_message(result or {}),
                active=active,
                required_downstream=required_downstream,
                graph_nodes=graph_nodes,
                state=state,
            )
            return
        self._apply_successful_graph_node_outcome(
            workflow_id=workflow_id,
            execution_id=execution_id,
            node_id=node_id,
            graph_node=graph_node,
            result=result,
            active=active,
            state=state,
        )

    def _apply_failed_graph_node_outcome(
        self,
        *,
        workflow_id: str,
        execution_id: str,
        node_id: str,
        graph_node: WorkflowGraphNode,
        result: dict[str, Any] | None,
        error: str,
        active: dict[str, dict[str, Any]],
        required_downstream: dict[str, list[str]],
        graph_nodes: dict[str, WorkflowGraphNode],
        state: _GraphRunState,
    ) -> None:
        state.failed.add(node_id)
        state.failed_nodes.append({"node_id": node_id, "error": error})
        graph_result = _failed_graph_result_for_scheduler(active.get(node_id), result, error=error)
        _update_graph_node_from_result(graph_node, graph_result)
        self._event_recorder.record_node_failed(
            workflow_id,
            execution_id,
            node_id,
            error=error,
            result=result,
        )
        self._block_required_downstream_nodes(
            workflow_id=workflow_id,
            execution_id=execution_id,
            failed_node_id=node_id,
            reason=f"upstream_failed:{node_id}",
            selected=state.selected,
            required_downstream=required_downstream,
            graph_nodes=graph_nodes,
            completed=state.completed,
            failed=state.failed,
            waiting=state.waiting,
            skipped=state.skipped,
            blocked=state.blocked,
            running=state.running_node_ids,
            blocked_nodes=state.blocked_nodes,
        )

    def _apply_successful_graph_node_outcome(
        self,
        *,
        workflow_id: str,
        execution_id: str,
        node_id: str,
        graph_node: WorkflowGraphNode,
        result: dict[str, Any],
        active: dict[str, dict[str, Any]],
        state: _GraphRunState,
    ) -> None:
        active[node_id] = result
        _update_graph_node_from_result(graph_node, result)
        state.executed_nodes.append(node_id)
        if result.get("status") == "waiting":
            self._record_waiting_graph_node(workflow_id, execution_id, node_id, result, state)
        elif result.get("status") == "skipped":
            self._record_skipped_graph_node(workflow_id, execution_id, node_id, result, state)
        else:
            self._record_completed_graph_node(workflow_id, execution_id, node_id, result, state)
        state.affected_downstream_nodes.extend(
            _new_items(
                state.affected_downstream_nodes,
                WorkflowNodeInputResolver(self._settings).update_downstream_resolved_inputs(
                    workflow_id,
                    node_id,
                ),
            )
        )

    def _record_waiting_graph_node(
        self,
        workflow_id: str,
        execution_id: str,
        node_id: str,
        result: dict[str, Any],
        state: _GraphRunState,
    ) -> None:
        state.waiting.add(node_id)
        state.waiting_nodes.append(node_id)
        if node_id not in state.stale_nodes:
            state.stale_nodes.append(node_id)
        self._event_recorder.record_node_waiting(
            workflow_id,
            execution_id,
            node_id,
            result=result,
        )

    def _record_skipped_graph_node(
        self,
        workflow_id: str,
        execution_id: str,
        node_id: str,
        result: dict[str, Any],
        state: _GraphRunState,
    ) -> None:
        state.skipped.add(node_id)
        state.skipped_nodes.append(node_id)
        state.skipped_reasons[node_id] = "node_service_skipped"
        self._event_recorder.record_node_skipped(
            workflow_id,
            execution_id,
            node_id,
            reason="node_service_skipped",
            result=result,
        )

    def _record_completed_graph_node(
        self,
        workflow_id: str,
        execution_id: str,
        node_id: str,
        result: dict[str, Any],
        state: _GraphRunState,
    ) -> None:
        state.completed.add(node_id)
        state.completed_nodes.append(node_id)
        self._event_recorder.record_node_completed(
            workflow_id,
            execution_id,
            node_id,
            result=result,
        )

    def _graph_scheduler_should_stop(self, state: _GraphRunState) -> bool:
        pending_node_ids = (
            state.selected
            - state.completed
            - state.failed
            - state.waiting
            - state.skipped
            - state.blocked
        )
        return not pending_node_ids or bool(state.waiting)

    def _block_unsatisfied_graph_scheduler_nodes(
        self,
        *,
        workflow_id: str,
        execution_id: str,
        active: dict[str, dict[str, Any]],
        graph_nodes: dict[str, WorkflowGraphNode],
        required_upstreams: dict[str, list[str]],
        state: _GraphRunState,
    ) -> bool:
        pending_node_ids = (
            state.selected
            - state.completed
            - state.failed
            - state.waiting
            - state.skipped
            - state.blocked
        )
        return self._block_unsatisfied_pending_nodes(
            workflow_id=workflow_id,
            execution_id=execution_id,
            pending_node_ids=pending_node_ids,
            required_upstreams=required_upstreams,
            skipped_reasons=state.skipped_reasons,
            active=active,
            graph_nodes=graph_nodes,
            completed=state.completed,
            failed=state.failed,
            waiting=state.waiting,
            skipped=state.skipped,
            blocked=state.blocked,
            blocked_nodes=state.blocked_nodes,
        )

    def _skip_graph_execution_node(
        self,
        workflow_id: str,
        execution_id: str | None,
        node_id: str,
        *,
        reason: str,
        graph_node: WorkflowGraphNode,
        active: dict[str, dict[str, Any]],
        active_result: dict[str, Any] | None,
        skipped: set[str],
        skipped_nodes: list[str],
        skipped_reasons: dict[str, str],
    ) -> None:
        skipped.add(node_id)
        skipped_nodes.append(node_id)
        skipped_reasons[node_id] = reason
        if active_result is None and (graph_node.output or graph_node.output_assets):
            active[node_id] = _graph_node_as_active_result(graph_node)
            active_result = active[node_id]
            self._event_recorder.record_node_skipped(
                workflow_id,
                execution_id,
                node_id,
                reason=reason,
                result=active_result,
            )

    def _execute_parallel_graph_node(
        self,
        *,
        workflow_id: str,
        node_id: str,
        node_type: str,
        ad_request: AdWorkflowGenerateRequest,
        request: WorkflowRunRequest,
        active: dict[str, dict[str, Any]],
        graph_node: WorkflowGraphNode,
        graph: WorkflowGraph,
    ) -> _ParallelNodeOutcome:
        try:
            result = self._execute_planned_node(
                workflow_id=workflow_id,
                node_type=node_type,
                ad_request=ad_request,
                request=request,
                active=active,
                graph_node=graph_node,
                graph=graph,
            )
        except (WorkflowNodeExecutionError, WorkflowNodeInputError) as exc:
            return _ParallelNodeOutcome(node_id=node_id, node_type=node_type, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - surfaced as per-node scheduler failure.
            return _ParallelNodeOutcome(node_id=node_id, node_type=node_type, error=str(exc))
        return _ParallelNodeOutcome(node_id=node_id, node_type=node_type, result=result)

    def _block_required_downstream_nodes(
        self,
        *,
        workflow_id: str,
        execution_id: str | None,
        failed_node_id: str,
        reason: str,
        selected: set[str],
        required_downstream: dict[str, list[str]],
        graph_nodes: dict[str, WorkflowGraphNode],
        completed: set[str],
        failed: set[str],
        waiting: set[str],
        skipped: set[str],
        blocked: set[str],
        running: set[str],
        blocked_nodes: list[str],
    ) -> None:
        for downstream_node_id in _required_reachable_downstream(
            failed_node_id,
            required_downstream,
        ):
            if downstream_node_id not in selected:
                continue
            if downstream_node_id in completed | failed | waiting | skipped | blocked | running:
                continue
            blocked.add(downstream_node_id)
            blocked_nodes.append(downstream_node_id)
            graph_node = graph_nodes[downstream_node_id]
            graph_node.status = "blocked"
            graph_node.stale = True
            graph_node.stale_reason = reason
            graph_node.metadata = dict(graph_node.metadata or {})
            graph_node.metadata["blocked_reason"] = reason
            self._event_recorder.record_node_blocked(
                workflow_id,
                execution_id,
                downstream_node_id,
                reason=reason,
            )

    def _block_unsatisfied_pending_nodes(
        self,
        *,
        workflow_id: str,
        execution_id: str | None,
        pending_node_ids: set[str],
        required_upstreams: dict[str, list[str]],
        skipped_reasons: dict[str, str],
        active: dict[str, dict[str, Any]],
        graph_nodes: dict[str, WorkflowGraphNode],
        completed: set[str],
        failed: set[str],
        waiting: set[str],
        skipped: set[str],
        blocked: set[str],
        blocked_nodes: list[str],
    ) -> bool:
        changed = False
        for node_id in sorted(pending_node_ids):
            unsatisfied = _unsatisfied_upstream_node_ids(
                node_id,
                required_upstreams=required_upstreams,
                selected=completed | failed | waiting | skipped | blocked | pending_node_ids,
                completed=completed,
                failed=failed,
                waiting=waiting,
                skipped=skipped,
                skipped_reasons=skipped_reasons,
                active=active,
                graph_nodes=graph_nodes,
                data_dir=self._settings.media_data_dir,
            )
            if not unsatisfied:
                continue
            reason = f"upstream_unsatisfied:{','.join(unsatisfied)}"
            blocked.add(node_id)
            blocked_nodes.append(node_id)
            graph_node = graph_nodes[node_id]
            graph_node.status = "blocked"
            graph_node.stale = True
            graph_node.stale_reason = reason
            graph_node.metadata = dict(graph_node.metadata or {})
            graph_node.metadata["blocked_reason"] = reason
            self._event_recorder.record_node_blocked(
                workflow_id,
                execution_id,
                node_id,
                reason=reason,
            )
            changed = True
        return changed
