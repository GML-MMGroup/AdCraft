from __future__ import annotations

from time import perf_counter

from app.core.config import Settings
from app.schemas.workflow_nodes import WorkflowNodeRunRequest, WorkflowNodeRunResponse
from app.schemas.workflow_revisions import WorkflowRevisionRequest
from app.services.agent_trace import utc_now
from app.services.media_paths import with_public_urls
from app.services.output_assets import dedupe_output_assets
from app.services.workflow_asset_history import select_existing_asset
from app.services.workflow_graph import update_graph_node_from_run_result
from app.services.workflow_input_resolver import WorkflowNodeInputResolver
from app.services.workflow_local_revisions import (
    WorkflowLocalRevisionError,
    WorkflowLocalRevisionService,
)
from app.services.workflow_node_asset_derivation import _apply_library_derivation_metadata
from app.services.workflow_node_errors import WorkflowNodeInputError
from app.services.workflow_node_response_builder import _node_response_from_revision_state
from app.services.workflow_node_result_store import WorkflowNodeResultStore
from app.services.workflow_node_run_preparation import (
    _has_request_asset_references,
    _request_node_id,
    _request_node_type,
)


class WorkflowNodeRevisionBridgeMixin:
    def _run_local_revision(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        node_run_id: str,
        existing_result: WorkflowNodeRunResponse | None,
        settings: Settings,
    ) -> WorkflowNodeRunResponse:
        node_id = _request_node_id(request)
        node_type = _request_node_type(request)
        if node_type == "final-composition":
            raise WorkflowNodeInputError("final-composition does not support media revision.")
        revision = request.revision
        if revision is None:
            raise WorkflowNodeInputError("revision request is required.")
        if revision.mode != "select_existing_asset":
            try:
                state = WorkflowLocalRevisionService(settings).create_revision(
                    workflow_id,
                    node_id,
                    WorkflowRevisionRequest(
                        **revision.model_dump(mode="json", exclude_none=True),
                        asset_references=list(request.asset_references),
                        library_entity_ids=list(request.library_entity_ids),
                        reference_mode=request.reference_mode,
                        provider=request.provider,
                        allow_provider_fallback=request.allow_provider_fallback,
                        provider_hints=dict(request.provider_hints or {}),
                        allow_optimizer_fallback=request.allow_optimizer_fallback,
                    ),
                )
            except WorkflowLocalRevisionError as exc:
                message = str(exc.detail.get("message") or exc.detail.get("code") or exc)
                raise WorkflowNodeInputError(message) from exc
            return _node_response_from_revision_state(
                state,
                existing_result=existing_result,
                workflow_id=workflow_id,
                node_id=node_id,
                node_type=node_type,
                node_run_id=node_run_id,
            )
        if existing_result is None:
            raise WorkflowNodeInputError(f"cannot revise {node_id}: active node result not found.")
        revision_request = request
        if _has_request_asset_references(request):
            revision_request = self._apply_request_asset_references(
                request.model_copy(
                    update={
                        "input_context": dict(existing_result.input_context),
                        "input_assets": list(existing_result.input_assets),
                    }
                ),
                workflow_id,
                settings,
            )
        started_at = utc_now().isoformat()
        started_counter = perf_counter()
        try:
            selected = select_existing_asset(
                data_dir=settings.media_data_dir,
                workflow_id=workflow_id,
                node_id=node_id,
                active_result=existing_result.model_dump(mode="json"),
                revision=revision.model_dump(mode="json", exclude_none=True),
                state_change_run_id=node_run_id,
                persist=request.save_outputs,
            )
        except ValueError as exc:
            raise WorkflowNodeInputError(str(exc)) from exc

        finished_at = utc_now().isoformat()
        duration_ms = round((perf_counter() - started_counter) * 1000)
        revision_context = (
            revision_request.input_context
            if _has_request_asset_references(revision_request)
            else existing_result.input_context
        )
        revision_assets = (
            revision_request.input_assets
            if _has_request_asset_references(revision_request)
            else existing_result.input_assets
        )
        selected_output = _apply_library_derivation_metadata(
            selected["output"],
            revision_context,
            target_entity_id=revision.target_entity_id,
            target_asset_id=revision.target_asset_id,
        )
        selected_output_assets = _apply_library_derivation_metadata(
            {"assets": selected["output_assets"]},
            revision_context,
            target_entity_id=revision.target_entity_id,
            target_asset_id=revision.target_asset_id,
        )["assets"]
        result = WorkflowNodeRunResponse(
            workflow_id=workflow_id,
            node_id=node_id,
            node_run_id=node_run_id,
            node_type=node_type,
            status="completed",
            output=selected_output,
            input_context=revision_context,
            input_assets=revision_assets,
            output_assets=with_public_urls(dedupe_output_assets(selected_output_assets)),
            error=None,
        )
        WorkflowNodeResultStore.preserve_existing_prompt_state(result, existing_result)
        self._attach_resolved_inputs(result, revision_request, result.input_assets, settings)
        persist_request = request.model_copy(
            update={
                "input_context": result.input_context,
                "input_assets": result.input_assets,
                "override_prompt": self._result_store.preserved_override_prompt(
                    request,
                    workflow_id,
                    node_id,
                    node_type,
                ),
            }
        )
        if request.save_outputs:
            trace_path = self._result_store.save_result(
                result,
                persist_request,
                started_at,
                finished_at,
                duration_ms,
            )
            result.trace_path = trace_path
            result.metadata_path = trace_path
            self._result_store.write_payload(
                result,
                persist_request,
                started_at,
                finished_at,
                duration_ms,
                active=True,
            )
            update_graph_node_from_run_result(
                data_dir=settings.media_data_dir,
                workflow_id=workflow_id,
                node_id=node_id,
                result=result.model_dump(mode="json"),
            )
            result.affected_downstream_nodes = WorkflowNodeInputResolver(
                settings
            ).update_downstream_resolved_inputs(
                workflow_id,
                node_id,
            )
        return result
