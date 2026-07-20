from __future__ import annotations

from time import perf_counter
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.schemas.workflow_nodes import (
    WorkflowNodeCatalogResponse,
    WorkflowNodeListResponse,
    WorkflowNodeRunRequest,
    WorkflowNodeRunResponse,
)
from app.services.agent_trace import utc_now
from app.services.media_inputs import convert_assets_for_model_input
from app.services.media_paths import with_public_urls
from app.services.workflow_node_catalog import (
    NODE_CATALOG as NODE_CATALOG,
    OPTIMIZER_AGENT_BY_NODE as OPTIMIZER_AGENT_BY_NODE,
    workflow_node_catalog_response,
)
from app.services.workflow_node_errors import (
    WorkflowNodeExecutionError,
    WorkflowNodeInputError,
)
from app.services.workflow_node_executor import WorkflowNodeExecutor
from app.services.workflow_node_persistence_bridge import WorkflowNodePersistenceBridgeMixin
from app.services.workflow_node_response_builder import WorkflowNodeResponseBuilderMixin
from app.services.workflow_node_result_store import WorkflowNodeResultStore
from app.services.workflow_node_revision_bridge import WorkflowNodeRevisionBridgeMixin
from app.services.workflow_node_run_preparation import (
    WorkflowNodeRunPreparationMixin,
    _request_node_id,
    _request_node_type,
)
from app.services.workflow_working_versions import WorkflowWorkingVersionService
from app.workflows.ad_workflow import create_workflow_id


class WorkflowNodeExecutionService(
    WorkflowNodeRunPreparationMixin,
    WorkflowNodeResponseBuilderMixin,
    WorkflowNodePersistenceBridgeMixin,
    WorkflowNodeRevisionBridgeMixin,
):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._result_store = WorkflowNodeResultStore(settings)
        self._executor = WorkflowNodeExecutor(settings)

    def catalog(self) -> WorkflowNodeCatalogResponse:
        return workflow_node_catalog_response()

    def run(self, request: WorkflowNodeRunRequest) -> WorkflowNodeRunResponse:
        workflow_id = request.workflow_id or create_workflow_id()
        settings = self._effective_settings(request)
        request = self._with_resolved_identity(request, workflow_id, settings)
        node_id = _request_node_id(request)
        node_type = _request_node_type(request)
        self._validate_supported_node_type(node_type)
        node_run_id = f"nrun_{uuid4().hex[:12]}"
        request = self._resolve_run_request_inputs(request, workflow_id, settings)
        existing_result = self._result_store.get_active_result(workflow_id, node_id, node_type)
        if request.revision is not None:
            return self._run_local_revision(
                request,
                workflow_id,
                node_run_id,
                existing_result,
                settings,
            )
        if self._should_skip_existing_result(request, workflow_id, node_type, existing_result):
            return existing_result.model_copy(update={"status": "skipped"})

        input_assets = with_public_urls(
            convert_assets_for_model_input(settings.media_data_dir, request.input_assets)
        )
        self._validate_required_inputs(node_type, request.input_context)
        started_at = utc_now().isoformat()
        started_counter = perf_counter()
        try:
            output = self._execute_and_normalize_output(
                request,
                workflow_id,
                node_id,
                node_type,
                settings,
                input_assets,
            )
        except WorkflowNodeInputError as exc:
            self._persist_reference_policy_failure(
                exc,
                request,
                workflow_id,
                node_id,
                node_type,
                node_run_id,
                input_assets,
                existing_result,
                settings,
                started_at,
                started_counter,
            )
            raise
        except Exception as exc:
            self._persist_execution_exception(
                exc,
                request,
                workflow_id,
                node_id,
                node_type,
                node_run_id,
                input_assets,
                existing_result,
                settings,
                started_at,
                started_counter,
            )
            raise WorkflowNodeExecutionError(str(exc)) from exc
        finished_at = utc_now().isoformat()
        duration_ms = round((perf_counter() - started_counter) * 1000)
        result = self._run_response_from_output(
            request,
            workflow_id,
            node_id,
            node_type,
            node_run_id,
            input_assets,
            output,
            settings,
        )
        self._attach_resolved_inputs(result, request, input_assets, settings)
        if request.save_outputs:
            self._persist_run_result(
                result,
                request,
                existing_result,
                settings,
                started_at,
                finished_at,
                duration_ms,
            )
        return WorkflowWorkingVersionService(settings).enrich_node_response(result)

    def list_nodes(self, workflow_id: str) -> WorkflowNodeListResponse:
        nodes = [
            WorkflowWorkingVersionService(self._settings).enrich_node_response(result)
            for result in self._result_store.list_results(workflow_id)
        ]
        return WorkflowNodeListResponse(workflow_id=workflow_id, nodes=nodes)

    def get_latest_node(self, workflow_id: str, node_id: str) -> WorkflowNodeRunResponse:
        result = self._result_store.get_active_result(workflow_id, node_id, node_id)
        if result is None:
            raise WorkflowNodeInputError(f"node result not found: {node_id}")
        return WorkflowWorkingVersionService(self._settings).enrich_node_response(result)

    def _execute_node(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        settings: Settings,
        input_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        executor = self._executor if settings is self._settings else WorkflowNodeExecutor(settings)
        return executor.execute(request, workflow_id, input_assets)
