from __future__ import annotations

from time import perf_counter
from typing import Any

from app.core.config import Settings
from app.schemas.workflow_nodes import WorkflowNodeRunRequest, WorkflowNodeRunResponse
from app.services.agent_trace import utc_now
from app.services.workflow_graph import update_graph_node_from_run_result
from app.services.workflow_input_resolver import WorkflowNodeInputResolver
from app.services.workflow_node_errors import ReferencePolicyInputError, WorkflowNodeInputError
from app.services.workflow_node_response_builder import (
    _is_final_candidate_pending_result,
    _is_optimize_only_result,
)
from app.services.workflow_node_result_store import WorkflowNodeResultStore


class WorkflowNodePersistenceBridgeMixin:
    def _persist_reference_policy_failure(
        self,
        exc: WorkflowNodeInputError,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        node_id: str,
        node_type: str,
        node_run_id: str,
        input_assets: list[dict[str, Any]],
        existing_result: WorkflowNodeRunResponse | None,
        settings: Settings,
        started_at: str,
        started_counter: float,
    ) -> None:
        if not isinstance(exc, ReferencePolicyInputError) or not request.save_outputs:
            return
        failed_result = self._failed_run_response(
            request,
            workflow_id,
            node_id,
            node_type,
            node_run_id,
            input_assets,
            output={"reference_policy": exc.policy},
            error=str(exc),
        )
        self._persist_failed_run_result(
            failed_result,
            request,
            existing_result,
            settings,
            started_at,
            started_counter,
        )

    def _persist_execution_exception(
        self,
        exc: Exception,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        node_id: str,
        node_type: str,
        node_run_id: str,
        input_assets: list[dict[str, Any]],
        existing_result: WorkflowNodeRunResponse | None,
        settings: Settings,
        started_at: str,
        started_counter: float,
    ) -> None:
        if not request.save_outputs:
            return
        failed_result = self._failed_run_response(
            request,
            workflow_id,
            node_id,
            node_type,
            node_run_id,
            input_assets,
            output={},
            error=str(exc),
        )
        self._persist_failed_run_result(
            failed_result,
            request,
            existing_result,
            settings,
            started_at,
            started_counter,
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

    def _persist_failed_run_result(
        self,
        failed_result: WorkflowNodeRunResponse,
        request: WorkflowNodeRunRequest,
        existing_result: WorkflowNodeRunResponse | None,
        settings: Settings,
        started_at: str,
        started_counter: float,
    ) -> None:
        finished_at = utc_now().isoformat()
        duration_ms = round((perf_counter() - started_counter) * 1000)
        self._attach_resolved_inputs(failed_result, request, failed_result.input_assets, settings)
        preserve_active = WorkflowNodeResultStore.result_has_active_output(existing_result)
        trace_path = self._result_store.save_result(
            failed_result,
            request,
            started_at,
            finished_at,
            duration_ms,
            active=not preserve_active,
        )
        failed_result.trace_path = trace_path
        failed_result.metadata_path = trace_path
        if preserve_active and existing_result is not None:
            self._result_store.annotate_preserved_active_failure(
                failed_result.workflow_id,
                failed_result.node_id,
                failed_result,
            )
        if request.workflow_id and not WorkflowNodeResultStore.defer_graph_updates(request):
            update_graph_node_from_run_result(
                data_dir=settings.media_data_dir,
                workflow_id=failed_result.workflow_id,
                node_id=failed_result.node_id,
                result=self._graph_result_for_persisted_run(
                    failed_result,
                    existing_result,
                    preserve_active,
                ),
            )

    def _persist_run_result(
        self,
        result: WorkflowNodeRunResponse,
        request: WorkflowNodeRunRequest,
        existing_result: WorkflowNodeRunResponse | None,
        settings: Settings,
        started_at: str,
        finished_at: str,
        duration_ms: int,
    ) -> None:
        optimize_only = _is_optimize_only_result(request, result.output)
        candidate_pending = _is_final_candidate_pending_result(result.node_type, result.output)
        preserve_active = (
            result.status == "failed"
            and WorkflowNodeResultStore.result_has_active_output(existing_result)
        )
        write_active = not preserve_active and not optimize_only and not candidate_pending
        trace_path = self._result_store.save_result(
            result,
            request,
            started_at,
            finished_at,
            duration_ms,
            active=write_active,
        )
        result.trace_path = trace_path
        result.metadata_path = trace_path
        if preserve_active and existing_result is not None:
            self._result_store.annotate_preserved_active_failure(
                result.workflow_id,
                result.node_id,
                result,
            )
        if self._should_update_graph_for_run(request, optimize_only, candidate_pending):
            update_graph_node_from_run_result(
                data_dir=settings.media_data_dir,
                workflow_id=result.workflow_id,
                node_id=result.node_id,
                result=self._graph_result_for_persisted_run(
                    result,
                    existing_result,
                    preserve_active,
                ),
            )
        if write_active and not WorkflowNodeResultStore.defer_graph_updates(request):
            result.affected_downstream_nodes = WorkflowNodeInputResolver(
                settings
            ).update_downstream_resolved_inputs(result.workflow_id, result.node_id)

    def _should_update_graph_for_run(
        self,
        request: WorkflowNodeRunRequest,
        optimize_only: bool,
        candidate_pending: bool,
    ) -> bool:
        return bool(
            request.workflow_id
            and not WorkflowNodeResultStore.defer_graph_updates(request)
            and not optimize_only
            and not candidate_pending
        )

    def _graph_result_for_persisted_run(
        self,
        result: WorkflowNodeRunResponse,
        existing_result: WorkflowNodeRunResponse | None,
        preserve_active: bool,
    ) -> dict[str, Any]:
        if preserve_active and existing_result is not None:
            return WorkflowNodeResultStore.failed_graph_result_preserving_active(
                existing_result,
                result,
            )
        return result.model_dump(mode="json")
