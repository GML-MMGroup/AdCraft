import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.schemas.workflow_nodes import WorkflowNodeRunResponse
from app.schemas.workflow_revisions import (
    WorkflowAssetHistoryResponse,
    WorkflowRevisionAcceptRequest,
    WorkflowRevisionListResponse,
    WorkflowRevisionRejectRequest,
    WorkflowRevisionRequest,
    WorkflowRevisionState,
)
from app.services.agent_trace import utc_now
from app.services.canvas_runtime_events import CanvasRuntimeEventService
from app.services.media_paths import with_public_urls
from app.services.workflow_asset_history import (
    apply_generated_revision_assets,
    load_node_asset_history,
    write_node_asset_history,
)
from app.services.workflow_graph import update_graph_node_from_run_result
from app.services.workflow_input_resolver import WorkflowNodeInputResolver
from app.services.workflow_node_identity import (
    ResolvedNodeIdentity,
    WorkflowNodeIdentityError,
    resolve_node_identity,
)
from app.services.workflow_prompt_target_metadata import (
    PromptTargetMetadataConflict,
    revision_request_with_normalized_metadata,
)
from app.services.workflow_quality_review import (
    SUPPORTED_QUALITY_REVIEW_NODES,
    WorkflowQualityReviewService,
)
from app.services.workflow_revision_acceptance import (
    append_warning_once,
    candidate_quality_failed,
    revision_has_quality_fields,
    revision_payload_from_state,
)
from app.services.workflow_revision_events import (
    WorkflowRevisionEventPublisher,
    sync_conversation_revision_action,
)
from app.services.workflow_revision_generation import (
    WorkflowRevisionGenerationHooks,
    WorkflowRevisionGenerationService,
)
from app.services.workflow_revision_store import (
    WorkflowRevisionStore,
    public_revision_metadata,
    server_revision_source_metadata,
)
from app.services.workflow_revision_targets import (
    active_assets,
    asset_entity_id,
    ensure_regenerate_target,
    revision_matches_asset_history,
    same_revision_target,
)
from app.services.workflow_state import resolve_active_result
from app.tools.media import build_media_provider


RESERVED_REVISION_METADATA_KEYS = {
    "source_type",
    "source_conversation_id",
    "source_action_id",
    "agent_conversation_id",
    "agent_action_id",
}


class WorkflowLocalRevisionError(ValueError):
    def __init__(self, *, status_code: int, detail: dict[str, Any]) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail.get("message") or detail.get("code") or "revision error"))


class WorkflowLocalRevisionService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._canvas_events = CanvasRuntimeEventService(settings.media_data_dir)
        self._store = WorkflowRevisionStore(settings.media_data_dir)
        self._revision_events = WorkflowRevisionEventPublisher(
            settings.media_data_dir,
            revision_states=self._revision_states,
        )
        self._generation = WorkflowRevisionGenerationService(
            settings,
            WorkflowRevisionGenerationHooks(
                complete_revision_from_selection=self._complete_revision_from_selection,
                ensure_candidate_quality=self._ensure_candidate_quality,
                sync_history_candidate_status=self._sync_history_candidate_status,
                enforce_visible_candidate_limit=self._enforce_visible_candidate_limit,
                write_state=self._write_state,
                append_event=self._append_event,
                emit_revision_status_changed=self._emit_revision_status_changed,
                emit_candidate_created=self._emit_candidate_created,
                emit_candidate_quality_updated=self._emit_candidate_quality_updated,
                emit_asset_history_updated=self._emit_asset_history_updated,
                emit_node_candidate_summary_updated=self._emit_node_candidate_summary_updated,
            ),
            provider_factory=build_media_provider,
        )

    def create_revision(
        self,
        workflow_id: str,
        node_id: str,
        request: WorkflowRevisionRequest,
        *,
        source_metadata: dict[str, Any] | None = None,
    ) -> WorkflowRevisionState:
        try:
            request = revision_request_with_normalized_metadata(request)
        except PromptTargetMetadataConflict as exc:
            raise WorkflowLocalRevisionError(status_code=422, detail=exc.detail) from exc
        identity = self._resolve_identity(workflow_id, node_id, None)
        if identity.node_type == "final-composition":
            raise WorkflowLocalRevisionError(
                status_code=422,
                detail={
                    "code": "local_revision_node_not_supported",
                    "message": "final-composition does not support media revision.",
                    "workflow_id": workflow_id,
                    "node_id": identity.node_id,
                    "node_type": identity.node_type,
                },
            )
        active = self._active_result(workflow_id, identity)
        if active is None:
            raise WorkflowLocalRevisionError(
                status_code=404,
                detail={
                    "code": "local_revision_target_not_found",
                    "message": f"Active node result not found: {identity.node_id}.",
                    "workflow_id": workflow_id,
                    "node_id": identity.node_id,
                },
            )
        if request.mode in {"regenerate_entity", "regenerate_asset"}:
            try:
                ensure_regenerate_target(identity, active, request)
            except ValueError as exc:
                self._raise_target_resolution_error(identity, exc)

        revision_id = f"rev_{uuid4().hex[:12]}"
        now = utc_now().isoformat()
        state = WorkflowRevisionState(
            workflow_id=workflow_id,
            node_id=identity.node_id,
            node_type=identity.node_type,
            revision_id=revision_id,
            status="queued",
            generation_status="queued",
            acceptance_status=(
                "not_required" if request.mode == "select_existing_asset" else "pending"
            ),
            visibility_status="visible",
            mode=request.mode,
            target_entity_id=request.target_entity_id,
            target_asset_id=request.target_asset_id,
            semantic_type=request.semantic_type,
            target_field=request.target_field,
            instruction=request.instruction,
            started_at=now,
            events_path=self._relative_events_path(workflow_id, identity.node_id, revision_id),
            trace_path=self._relative_state_path(workflow_id, identity.node_id, revision_id),
            metadata={
                **public_revision_metadata(request.metadata),
                **server_revision_source_metadata(source_metadata),
            },
        )
        self._write_state(state)
        self._append_event(state, "revision_queued", {})
        state.status = "running"
        state.generation_status = "running"
        self._write_state(state)
        self._append_event(state, "revision_started", {})
        self._emit_revision_status_changed(state)

        try:
            if request.mode == "select_existing_asset":
                state = self._generation.select_existing_asset(identity, active, request, state)
            elif request.mode in {"regenerate_entity", "regenerate_asset"}:
                state = self._generation.regenerate_asset(identity, active, request, state)
            else:
                raise WorkflowLocalRevisionError(
                    status_code=422,
                    detail={
                        "code": "local_revision_mode_not_supported",
                        "message": f"Unsupported local revision mode: {request.mode}.",
                        "workflow_id": workflow_id,
                        "node_id": identity.node_id,
                        "mode": request.mode,
                    },
                )
        except WorkflowLocalRevisionError:
            raise
        except ValueError as exc:
            if hasattr(exc, "detail") and hasattr(exc, "status_code"):
                raise WorkflowLocalRevisionError(
                    status_code=getattr(exc, "status_code", 422),
                    detail=getattr(exc, "detail"),
                ) from exc
            state.status = "failed"
            state.generation_status = "failed"
            state.error = str(exc)
            state.finished_at = utc_now().isoformat()
            self._write_state(state)
            self._append_event(state, "revision_failed", {"error": state.error})
            self._emit_revision_status_changed(state)
            self._emit_node_candidate_summary_updated(state)
        return state

    def list_revisions(self, workflow_id: str, node_id: str) -> WorkflowRevisionListResponse:
        states = self._revision_states(workflow_id, node_id)
        return WorkflowRevisionListResponse(
            workflow_id=workflow_id,
            node_id=node_id,
            revisions=states,
        )

    def get_revision(
        self, workflow_id: str, node_id: str, revision_id: str
    ) -> WorkflowRevisionState:
        state_path = self._store.state_path(workflow_id, node_id, revision_id)
        if not state_path.exists():
            raise WorkflowLocalRevisionError(
                status_code=404,
                detail={
                    "code": "local_revision_not_found",
                    "message": f"Local revision not found: {revision_id}.",
                    "workflow_id": workflow_id,
                    "node_id": node_id,
                    "revision_id": revision_id,
                },
            )
        return WorkflowRevisionState.model_validate_json(state_path.read_text(encoding="utf-8"))

    def accept_revision(
        self,
        workflow_id: str,
        node_id: str,
        revision_id: str,
        request: WorkflowRevisionAcceptRequest,
    ) -> WorkflowRevisionState:
        identity = self._resolve_identity(workflow_id, node_id, None)
        state = self.get_revision(workflow_id, identity.node_id, revision_id)
        if state.acceptance_status == "accepted":
            return state
        if state.acceptance_status in {"rejected", "superseded"}:
            raise WorkflowLocalRevisionError(
                status_code=409,
                detail={
                    "code": "candidate_accept_conflict",
                    "message": f"Revision candidate is already {state.acceptance_status}.",
                    "workflow_id": workflow_id,
                    "node_id": identity.node_id,
                    "revision_id": revision_id,
                    "acceptance_status": state.acceptance_status,
                },
            )
        if (state.generation_status or state.status) != "completed":
            raise WorkflowLocalRevisionError(
                status_code=409,
                detail={
                    "code": "candidate_not_ready",
                    "message": "Revision candidate must be completed before it can be accepted.",
                    "workflow_id": workflow_id,
                    "node_id": identity.node_id,
                    "revision_id": revision_id,
                    "generation_status": state.generation_status or state.status,
                },
            )
        if not state.candidate_assets:
            raise WorkflowLocalRevisionError(
                status_code=422,
                detail={
                    "code": "candidate_assets_missing",
                    "message": "Revision candidate has no candidate assets to accept.",
                    "workflow_id": workflow_id,
                    "node_id": identity.node_id,
                    "revision_id": revision_id,
                },
            )
        active = self._active_result(workflow_id, identity)
        if active is None:
            raise WorkflowLocalRevisionError(
                status_code=404,
                detail={
                    "code": "local_revision_target_not_found",
                    "message": f"Active node result not found: {identity.node_id}.",
                    "workflow_id": workflow_id,
                    "node_id": identity.node_id,
                },
            )
        quality_was_missing = not revision_has_quality_fields(state)
        state = self._ensure_candidate_quality(identity, active, state)
        if quality_was_missing and revision_has_quality_fields(state):
            self._write_state(state)
            self._emit_candidate_quality_updated(state)
            self._emit_node_candidate_summary_updated(state)
        if candidate_quality_failed(state) and not request.override_quality_failure:
            self._write_state(state)
            raise WorkflowLocalRevisionError(
                status_code=409,
                detail={
                    "code": "candidate_quality_blocked",
                    "message": "Candidate quality failed; pass override_quality_failure=true to accept.",
                    "workflow_id": workflow_id,
                    "node_id": identity.node_id,
                    "revision_id": revision_id,
                },
            )
        if candidate_quality_failed(state) and request.override_quality_failure:
            append_warning_once(
                state,
                {
                    "code": "candidate_quality_failed_overridden",
                    "message": "Candidate quality failure was accepted by explicit user override.",
                },
            )
        accepted_candidates = [
            {
                **asset,
                "candidate_status": "accepted",
                "acceptance_status": "accepted",
                "visibility_status": "visible",
                "is_active": True,
                "library_suggested": True,
            }
            for asset in state.candidate_assets
        ]
        selected = apply_generated_revision_assets(
            data_dir=self._settings.media_data_dir,
            workflow_id=identity.workflow_id,
            node_id=identity.node_id,
            active_result=active,
            revision=revision_payload_from_state(state),
            generated_assets=accepted_candidates,
            state_change_run_id=state.revision_id,
            persist=True,
        )
        state.acceptance_status = "accepted"
        state.visibility_status = "visible"
        state.note = request.note or state.note
        state.candidate_assets = accepted_candidates
        state.previous_active_asset_id = (
            selected.get("previous_active_asset_id") or state.previous_active_asset_id
        )
        state.previous_active_asset_ids = selected.get("previous_active_asset_ids") or (
            [state.previous_active_asset_id] if state.previous_active_asset_id else []
        )
        accepted_asset_ids = [
            str(asset.get("asset_id") or "")
            for asset in state.candidate_assets
            if asset.get("asset_id")
        ]
        state.metadata["candidate_asset_ids"] = accepted_asset_ids
        state.metadata["accepted_asset_ids"] = accepted_asset_ids
        state.metadata["primary_candidate_asset_id"] = state.new_asset_id
        node_run = self._persist_node_run(
            identity,
            active,
            WorkflowRevisionRequest(**revision_payload_from_state(state)),
            state,
            selected,
        )
        state.node = node_run.model_dump(mode="json")
        state.affected_downstream_nodes = node_run.affected_downstream_nodes
        state.finished_at = utc_now().isoformat()
        self._write_state(state)
        self._sync_history_candidate_status(state)
        self._supersede_other_pending_candidates(state)
        self._append_event(
            state,
            "revision_candidate_accepted",
            {
                "note": state.note,
                "new_asset_id": state.new_asset_id,
                "accepted_asset_ids": accepted_asset_ids,
                "affected_downstream_nodes": state.affected_downstream_nodes,
            },
        )
        sync_conversation_revision_action(self._settings.media_data_dir, state, status="accepted")
        self._emit_candidate_accepted(state)
        self._emit_asset_history_updated(state, active_asset_ids=accepted_asset_ids)
        self._emit_node_candidate_summary_updated(state)
        self._emit_resolved_inputs_updated(state)
        return state

    def reject_revision(
        self,
        workflow_id: str,
        node_id: str,
        revision_id: str,
        request: WorkflowRevisionRejectRequest,
    ) -> WorkflowRevisionState:
        identity = self._resolve_identity(workflow_id, node_id, None)
        state = self.get_revision(workflow_id, identity.node_id, revision_id)
        if state.acceptance_status == "rejected":
            return state
        if state.acceptance_status == "accepted":
            raise WorkflowLocalRevisionError(
                status_code=409,
                detail={
                    "code": "candidate_reject_conflict",
                    "message": "Accepted revision candidates cannot be rejected.",
                    "workflow_id": workflow_id,
                    "node_id": identity.node_id,
                    "revision_id": revision_id,
                },
            )
        state.acceptance_status = "rejected"
        state.visibility_status = "archived"
        state.rejection_reason = request.reason or state.rejection_reason
        state.candidate_assets = [
            {
                **asset,
                "candidate_status": "rejected",
                "acceptance_status": "rejected",
                "visibility_status": "archived",
            }
            for asset in state.candidate_assets
        ]
        rejected_asset_ids = [
            str(asset.get("asset_id") or "")
            for asset in state.candidate_assets
            if asset.get("asset_id")
        ]
        state.metadata["candidate_asset_ids"] = rejected_asset_ids
        state.metadata["rejected_asset_ids"] = rejected_asset_ids
        state.metadata["primary_candidate_asset_id"] = state.new_asset_id
        state.finished_at = state.finished_at or utc_now().isoformat()
        self._write_state(state)
        self._sync_history_candidate_status(state)
        self._append_event(
            state,
            "revision_candidate_rejected",
            {"reason": state.rejection_reason},
        )
        sync_conversation_revision_action(self._settings.media_data_dir, state, status="rejected")
        self._emit_candidate_rejected(state)
        self._emit_asset_history_updated(state)
        self._emit_node_candidate_summary_updated(state)
        return state

    def asset_history(
        self,
        workflow_id: str,
        node_id: str,
        *,
        entity_id: str,
        semantic_type: str,
    ) -> WorkflowAssetHistoryResponse:
        assets = [
            asset
            for asset in load_node_asset_history(
                self._settings.media_data_dir, workflow_id, node_id
            )
            if asset_entity_id(asset) == entity_id
            and str(asset.get("semantic_type") or "") == semantic_type
        ]
        if not assets:
            active = resolve_active_result(
                self._settings.media_data_dir,
                workflow_id,
                node_id,
            )
            assets = [
                asset
                for asset in active_assets(active or {})
                if asset_entity_id(asset) == entity_id
                and str(asset.get("semantic_type") or "") == semantic_type
            ]
        if not assets:
            raise WorkflowLocalRevisionError(
                status_code=404,
                detail={
                    "code": "asset_history_not_found",
                    "message": "Asset history not found for target.",
                    "workflow_id": workflow_id,
                    "node_id": node_id,
                    "entity_id": entity_id,
                    "semantic_type": semantic_type,
                },
            )
        active_asset_id = next(
            (str(asset.get("asset_id")) for asset in assets if asset.get("is_active") is True),
            None,
        )
        revisions = [
            state
            for state in self._revision_states(workflow_id, node_id)
            if revision_matches_asset_history(state, entity_id, semantic_type)
        ]
        return WorkflowAssetHistoryResponse(
            workflow_id=workflow_id,
            node_id=node_id,
            entity_id=entity_id,
            semantic_type=semantic_type,
            active_asset_id=active_asset_id,
            assets=with_public_urls(assets),
            revisions=revisions,
        )

    def _complete_revision_from_selection(
        self,
        identity: ResolvedNodeIdentity,
        active: dict[str, Any],
        request: WorkflowRevisionRequest,
        state: WorkflowRevisionState,
        selected: dict[str, Any],
    ) -> WorkflowRevisionState:
        state.previous_active_asset_id = (
            selected.get("previous_active_asset_id") or state.previous_active_asset_id
        )
        selected_asset = selected.get("selected_asset") if isinstance(selected, dict) else None
        if isinstance(selected_asset, dict):
            state.new_asset_id = str(selected_asset.get("asset_id") or "")
        node_run = self._persist_node_run(identity, active, request, state, selected)
        state.status = "completed"
        state.generation_status = "completed"
        if state.mode == "select_existing_asset":
            state.acceptance_status = "not_required"
        elif state.acceptance_status == "not_required":
            state.acceptance_status = "accepted"
        state.finished_at = utc_now().isoformat()
        state.node = node_run.model_dump(mode="json")
        state.affected_downstream_nodes = node_run.affected_downstream_nodes
        self._write_state(state)
        self._append_event(
            state,
            "revision_completed",
            {
                "previous_active_asset_id": state.previous_active_asset_id,
                "new_asset_id": state.new_asset_id,
            },
        )
        self._emit_revision_status_changed(state)
        self._emit_asset_history_updated(state)
        self._emit_resolved_inputs_updated(state)
        return state

    def _persist_node_run(
        self,
        identity: ResolvedNodeIdentity,
        active: dict[str, Any],
        request: WorkflowRevisionRequest,
        state: WorkflowRevisionState,
        selected: dict[str, Any],
    ) -> WorkflowNodeRunResponse:
        node_run_id = f"nrun_{uuid4().hex[:12]}"
        output = selected["output"]
        output_assets = with_public_urls(selected["output_assets"])
        input_context = dict(active.get("input_context") or {})
        if identity.node_type in SUPPORTED_QUALITY_REVIEW_NODES:
            output, output_assets, _quality_summary = WorkflowQualityReviewService(
                self._settings
            ).review_node_output(
                identity.workflow_id,
                identity.node_id,
                identity.node_type,
                output,
                output_assets,
                input_context,
            )
        node_run = WorkflowNodeRunResponse(
            workflow_id=identity.workflow_id,
            node_id=identity.node_id,
            node_run_id=node_run_id,
            node_type=identity.node_type,
            status="completed",
            output=output,
            input_context=input_context,
            input_assets=list(active.get("input_assets") or []),
            output_assets=output_assets,
            error=None,
            affected_downstream_nodes=[],
            stale=False,
            has_active_output=True,
        )
        relative_path = (
            Path("runs") / identity.workflow_id / "nodes" / identity.node_id / f"{node_run_id}.json"
        )
        node_run.trace_path = relative_path.as_posix()
        node_run.metadata_path = relative_path.as_posix()
        node_dir = (
            self._settings.media_data_dir
            / "runs"
            / identity.workflow_id
            / "nodes"
            / identity.node_id
        )
        node_dir.mkdir(parents=True, exist_ok=True)
        for existing_path in node_dir.glob("nrun_*.json"):
            try:
                payload = json.loads(existing_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            payload["active"] = False
            existing_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        now = utc_now().isoformat()
        payload = {
            **node_run.model_dump(mode="json"),
            "override_prompt": active.get("override_prompt"),
            "started_at": state.started_at,
            "finished_at": now,
            "duration_ms": 0,
            "active": True,
            "source": "workflow-local-revision",
            "revision_id": state.revision_id,
            "trace": {
                "source": "workflow-local-revision",
                "input_context": input_context,
                "input_assets": node_run.input_assets,
                "output": output,
                "output_assets": output_assets,
                "revision": request.model_dump(mode="json"),
                "optimizedRevisionPrompt": state.optimizedRevisionPrompt,
                "providerRevisionPrompt": state.providerRevisionPrompt,
                "error": None,
            },
        }
        output_path = self._settings.media_data_dir / relative_path
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (node_dir / "active.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        update_graph_node_from_run_result(
            data_dir=self._settings.media_data_dir,
            workflow_id=identity.workflow_id,
            node_id=identity.node_id,
            result=node_run.model_dump(mode="json"),
        )
        node_run.affected_downstream_nodes = WorkflowNodeInputResolver(
            self._settings
        ).update_downstream_resolved_inputs(identity.workflow_id, identity.node_id)
        return node_run

    def _resolve_identity(
        self, workflow_id: str, node_id: str, node_type: str | None
    ) -> ResolvedNodeIdentity:
        try:
            return resolve_node_identity(
                data_dir=self._settings.media_data_dir,
                workflow_id=workflow_id,
                node_id=node_id,
                node_type=node_type,
            )
        except WorkflowNodeIdentityError as exc:
            active = resolve_active_result(
                self._settings.media_data_dir, workflow_id, node_id, node_type
            )
            if active is None:
                raise exc
            return ResolvedNodeIdentity(
                workflow_id=workflow_id,
                node_id=node_id,
                node_type=str(active.get("node_type") or node_type or node_id),
                graph_node=None,
                legacy_node_type_fallback=False,
            )

    def _active_result(
        self, workflow_id: str, identity: ResolvedNodeIdentity
    ) -> dict[str, Any] | None:
        return resolve_active_result(
            self._settings.media_data_dir,
            workflow_id,
            identity.node_id,
            identity.node_type,
        )

    def _raise_target_resolution_error(
        self,
        identity: ResolvedNodeIdentity,
        exc: ValueError,
    ) -> None:
        detail = getattr(exc, "detail", None)
        status_code = getattr(exc, "status_code", 422)
        if not isinstance(detail, dict):
            message = str(exc)
            detail = {
                "code": (
                    "local_revision_target_ambiguous"
                    if "ambiguous" in message
                    else "local_revision_target_not_found"
                ),
                "message": message,
                "workflow_id": identity.workflow_id,
                "node_id": identity.node_id,
                "node_type": identity.node_type,
            }
        raise WorkflowLocalRevisionError(status_code=status_code, detail=detail) from exc

    def _ensure_candidate_quality(
        self,
        identity: ResolvedNodeIdentity,
        active: dict[str, Any],
        state: WorkflowRevisionState,
    ) -> WorkflowRevisionState:
        if not state.candidate_assets:
            return state
        if (
            all("quality_status" in asset for asset in state.candidate_assets)
            and state.quality_summary
        ):
            return state
        input_context = (
            active.get("input_context") if isinstance(active.get("input_context"), dict) else {}
        )
        candidate_output = {
            "assets": state.candidate_assets,
            "output_assets": state.candidate_assets,
            "status": "candidate_pending",
        }
        reviewed_output, reviewed_assets, summary = WorkflowQualityReviewService(
            self._settings
        ).review_node_output(
            identity.workflow_id,
            identity.node_id,
            identity.node_type,
            candidate_output,
            state.candidate_assets,
            input_context,
        )
        state.candidate_assets = reviewed_assets
        state.candidate_output = reviewed_output
        state.quality_summary = summary.model_dump(mode="json")
        return state

    def _sync_history_candidate_status(self, state: WorkflowRevisionState) -> None:
        if not state.candidate_assets:
            return
        history = load_node_asset_history(
            self._settings.media_data_dir, state.workflow_id, state.node_id
        )
        candidate_by_id = {
            str(asset.get("asset_id") or ""): asset for asset in state.candidate_assets
        }
        updated: list[dict[str, Any]] = []
        for asset in history:
            asset_id = str(asset.get("asset_id") or "")
            if asset_id in candidate_by_id:
                merged = {**asset, **candidate_by_id[asset_id]}
                updated.append(merged)
            else:
                updated.append(asset)
        write_node_asset_history(
            self._settings.media_data_dir, state.workflow_id, state.node_id, updated
        )

    def _supersede_other_pending_candidates(self, accepted_state: WorkflowRevisionState) -> None:
        for state in self._revision_states(accepted_state.workflow_id, accepted_state.node_id):
            if state.revision_id == accepted_state.revision_id:
                continue
            if not same_revision_target(state, accepted_state):
                continue
            if state.acceptance_status != "pending":
                continue
            state.acceptance_status = "superseded"
            state.visibility_status = "archived"
            state.candidate_assets = [
                {
                    **asset,
                    "candidate_status": "superseded",
                    "acceptance_status": "superseded",
                    "visibility_status": "archived",
                }
                for asset in state.candidate_assets
            ]
            self._write_state(state)
            self._sync_history_candidate_status(state)
            self._append_event(
                state,
                "revision_candidate_superseded",
                {"accepted_revision_id": accepted_state.revision_id},
            )
            self._emit_candidate_superseded(state, superseded_by=accepted_state)
            self._emit_asset_history_updated(state)
            self._emit_node_candidate_summary_updated(state)

    def _enforce_visible_candidate_limit(self, newest_state: WorkflowRevisionState) -> None:
        same_target = [
            state
            for state in self._revision_states(newest_state.workflow_id, newest_state.node_id)
            if same_revision_target(state, newest_state) and state.acceptance_status == "pending"
        ]
        same_target.sort(key=lambda state: state.started_at)
        visible_revision_ids = {state.revision_id for state in same_target[-5:]}
        for state in same_target:
            visibility = "visible" if state.revision_id in visible_revision_ids else "archived"
            if state.visibility_status == visibility:
                continue
            state.visibility_status = visibility
            state.candidate_assets = [
                {
                    **asset,
                    "visibility_status": visibility,
                }
                for asset in state.candidate_assets
            ]
            self._write_state(state)
            self._sync_history_candidate_status(state)

    def _revision_states(self, workflow_id: str, node_id: str) -> list[WorkflowRevisionState]:
        return self._store.revision_states(workflow_id, node_id)

    def _write_state(self, state: WorkflowRevisionState) -> None:
        self._store.write_state(state)

    def _append_event(
        self, state: WorkflowRevisionState, event_type: str, payload: dict[str, Any]
    ) -> None:
        self._store.append_event(state, event_type, payload)

    def _emit_revision_status_changed(
        self,
        state: WorkflowRevisionState,
        *,
        waiting_reason: str | None = None,
    ) -> None:
        self._revision_events.emit_revision_status_changed(
            state,
            waiting_reason=waiting_reason,
        )

    def _emit_candidate_created(self, state: WorkflowRevisionState) -> None:
        self._revision_events.emit_candidate_created(state)

    def _emit_candidate_quality_updated(self, state: WorkflowRevisionState) -> None:
        self._revision_events.emit_candidate_quality_updated(state)

    def _emit_candidate_accepted(self, state: WorkflowRevisionState) -> None:
        self._revision_events.emit_candidate_accepted(state)

    def _emit_candidate_rejected(self, state: WorkflowRevisionState) -> None:
        self._revision_events.emit_candidate_rejected(state)

    def _emit_candidate_superseded(
        self,
        state: WorkflowRevisionState,
        *,
        superseded_by: WorkflowRevisionState,
    ) -> None:
        self._revision_events.emit_candidate_superseded(state, superseded_by=superseded_by)

    def _emit_asset_history_updated(
        self,
        state: WorkflowRevisionState,
        *,
        active_asset_ids: list[str] | None = None,
    ) -> None:
        self._revision_events.emit_asset_history_updated(
            state,
            active_asset_ids=active_asset_ids,
        )

    def _emit_node_candidate_summary_updated(self, state: WorkflowRevisionState) -> None:
        self._revision_events.emit_node_candidate_summary_updated(state)

    def _emit_resolved_inputs_updated(self, state: WorkflowRevisionState) -> None:
        self._revision_events.emit_resolved_inputs_updated(state)

    def _relative_state_path(self, workflow_id: str, node_id: str, revision_id: str) -> str:
        return self._store.relative_state_path(workflow_id, node_id, revision_id)

    def _relative_events_path(self, workflow_id: str, node_id: str, revision_id: str) -> str:
        return self._store.relative_events_path(workflow_id, node_id, revision_id)
