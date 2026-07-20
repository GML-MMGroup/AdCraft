from dataclasses import dataclass
from typing import Any, Callable

from app.core.config import Settings
from app.schemas.workflow_revisions import WorkflowRevisionRequest, WorkflowRevisionState
from app.services.agent_trace import utc_now
from app.services.workflow_asset_history import (
    prepare_generated_revision_candidates,
    select_existing_asset,
)
from app.services.workflow_asset_library_ingest import WorkflowAssetLibraryIngestService
from app.services.workflow_node_identity import ResolvedNodeIdentity
from app.services.workflow_prompt_optimizer import (
    WorkflowPromptOptimizerError,
    WorkflowPromptOptimizerService,
)
from app.services.workflow_revision_acceptance import (
    revision_asset_is_ready,
    revision_has_quality_fields,
)
from app.services.workflow_revision_provider_candidates import (
    provider_revision_assets,
    revision_prompt_request,
)
from app.services.workflow_revision_targets import resolve_revision_target, target_resolution_error
from app.tools.media import build_media_provider


@dataclass(frozen=True)
class WorkflowRevisionGenerationHooks:
    complete_revision_from_selection: Callable[
        [
            ResolvedNodeIdentity,
            dict[str, Any],
            WorkflowRevisionRequest,
            WorkflowRevisionState,
            dict[str, Any],
        ],
        WorkflowRevisionState,
    ]
    ensure_candidate_quality: Callable[
        [ResolvedNodeIdentity, dict[str, Any], WorkflowRevisionState],
        WorkflowRevisionState,
    ]
    sync_history_candidate_status: Callable[[WorkflowRevisionState], None]
    enforce_visible_candidate_limit: Callable[[WorkflowRevisionState], None]
    write_state: Callable[[WorkflowRevisionState], None]
    append_event: Callable[[WorkflowRevisionState, str, dict[str, Any]], None]
    emit_revision_status_changed: Callable[..., None]
    emit_candidate_created: Callable[[WorkflowRevisionState], None]
    emit_candidate_quality_updated: Callable[[WorkflowRevisionState], None]
    emit_asset_history_updated: Callable[[WorkflowRevisionState], None]
    emit_node_candidate_summary_updated: Callable[[WorkflowRevisionState], None]


class WorkflowRevisionGenerationService:
    def __init__(
        self,
        settings: Settings,
        hooks: WorkflowRevisionGenerationHooks,
        *,
        provider_factory: Any = build_media_provider,
    ) -> None:
        self._settings = settings
        self._hooks = hooks
        self._provider_factory = provider_factory

    def select_existing_asset(
        self,
        identity: ResolvedNodeIdentity,
        active: dict[str, Any],
        request: WorkflowRevisionRequest,
        state: WorkflowRevisionState,
    ) -> WorkflowRevisionState:
        selected = select_existing_asset(
            data_dir=self._settings.media_data_dir,
            workflow_id=identity.workflow_id,
            node_id=identity.node_id,
            active_result=active,
            revision=request.model_dump(mode="json", exclude_none=True),
            state_change_run_id=state.revision_id,
            persist=True,
        )
        return self._hooks.complete_revision_from_selection(
            identity, active, request, state, selected
        )

    def regenerate_asset(
        self,
        identity: ResolvedNodeIdentity,
        active: dict[str, Any],
        request: WorkflowRevisionRequest,
        state: WorkflowRevisionState,
    ) -> WorkflowRevisionState:
        try:
            target = resolve_revision_target(
                active, request.model_dump(mode="json", exclude_none=True)
            )
        except ValueError as exc:
            raise target_resolution_error(identity, str(exc)) from exc
        self._apply_target_to_state(state, target)
        try:
            optimization = WorkflowPromptOptimizerService(self._settings).optimize(
                revision_prompt_request(identity, active, target, request, self._settings)
            )
        except WorkflowPromptOptimizerError as exc:
            return self._fail_revision(state, f"{exc.code}: {exc}")
        state.optimizedRevisionPrompt = optimization.optimized_generation_prompt
        state.providerRevisionPrompt = optimization.provider_prompt
        state.warnings = [*state.warnings, *optimization.warnings]
        state.revisionRequirements = {
            "instruction": request.instruction or "",
            "target": target,
            "node_id": identity.node_id,
            "node_type": identity.node_type,
            "asset_references": [item.model_dump(mode="json") for item in request.asset_references],
            "selected_skill_ids": optimization.selected_skill_ids,
            "quality_notes": optimization.quality_notes,
            "negative_prompt": optimization.negative_prompt,
            "warnings": optimization.warnings,
            "mock_mode": optimization.mock_mode,
        }
        if request.provider_hints.get("simulate_failure"):
            return self._fail_revision(state, "Local revision provider failed.")
        if request.provider_hints.get("simulate_waiting") and identity.node_type in {
            "storyboard-video-generation",
            "bgm",
            "storyboard",
            "character-generation",
            "scene-generation",
        }:
            return self._waiting_revision(state)

        generated_assets = provider_revision_assets(
            self._settings,
            identity,
            target,
            state,
            request,
            active,
            provider_factory=self._provider_factory,
        )
        waiting_asset = next(
            (asset for asset in generated_assets if not revision_asset_is_ready(asset)),
            None,
        )
        if waiting_asset is not None and identity.node_type in {
            "storyboard-video-generation",
            "bgm",
        }:
            state.status = "waiting"
            state.generation_status = "waiting"
            state.new_asset_id = str(waiting_asset.get("asset_id") or "") or None
            state.metadata["pending_asset"] = waiting_asset
            state.metadata["pending_assets"] = generated_assets
            self._hooks.write_state(state)
            self._hooks.append_event(state, "revision_waiting", {"assets": generated_assets})
            self._hooks.emit_revision_status_changed(state, waiting_reason="provider_task_pending")
            self._hooks.emit_node_candidate_summary_updated(state)
            return state
        if waiting_asset is not None:
            raise ValueError("Local revision provider did not return a ready asset.")
        return self._complete_candidate_revision(identity, active, request, state, generated_assets)

    def _apply_target_to_state(
        self,
        state: WorkflowRevisionState,
        target: dict[str, Any],
    ) -> None:
        state.target_entity_id = state.target_entity_id or target["entity_id"]
        state.semantic_type = state.semantic_type or target["semantic_type"]
        state.target_asset_id = state.target_asset_id or target.get("asset_id")
        state.target_field = target.get("target_field") or state.target_field
        state.previous_active_asset_id = target.get("asset_id")

    def _fail_revision(
        self,
        state: WorkflowRevisionState,
        error: str,
    ) -> WorkflowRevisionState:
        state.status = "failed"
        state.generation_status = "failed"
        state.error = error
        state.finished_at = utc_now().isoformat()
        self._hooks.write_state(state)
        self._hooks.append_event(state, "revision_failed", {"error": state.error})
        self._hooks.emit_revision_status_changed(state)
        self._hooks.emit_node_candidate_summary_updated(state)
        return state

    def _waiting_revision(self, state: WorkflowRevisionState) -> WorkflowRevisionState:
        state.status = "waiting"
        state.generation_status = "waiting"
        state.error = None
        self._hooks.write_state(state)
        self._hooks.append_event(state, "revision_waiting", {})
        self._hooks.emit_revision_status_changed(state, waiting_reason="provider_task_pending")
        self._hooks.emit_node_candidate_summary_updated(state)
        return state

    def _complete_candidate_revision(
        self,
        identity: ResolvedNodeIdentity,
        active: dict[str, Any],
        request: WorkflowRevisionRequest,
        state: WorkflowRevisionState,
        generated_assets: list[dict[str, Any]],
    ) -> WorkflowRevisionState:
        candidate = prepare_generated_revision_candidates(
            data_dir=self._settings.media_data_dir,
            workflow_id=identity.workflow_id,
            node_id=identity.node_id,
            active_result=active,
            revision={
                **request.model_dump(mode="json", exclude_none=True),
                "target_entity_id": state.target_entity_id,
                "semantic_type": state.semantic_type,
                "target_field": state.target_field,
                "instruction": request.instruction,
                "optimizedRevisionPrompt": state.optimizedRevisionPrompt,
                "providerRevisionPrompt": state.providerRevisionPrompt,
                "revisionRequirements": state.revisionRequirements,
            },
            generated_assets=generated_assets,
            state_change_run_id=state.revision_id,
            persist=True,
        )
        candidate_assets = candidate["candidate_assets"]
        state.previous_active_asset_id = (
            candidate.get("previous_active_asset_id") or state.previous_active_asset_id
        )
        state.previous_active_asset_ids = candidate.get("previous_active_asset_ids") or (
            [state.previous_active_asset_id] if state.previous_active_asset_id else []
        )
        state.new_asset_id = str(candidate_assets[0].get("asset_id") or "") or None
        candidate_asset_ids = [
            str(asset.get("asset_id") or "") for asset in candidate_assets if asset.get("asset_id")
        ]
        state.metadata["candidate_asset_ids"] = candidate_asset_ids
        state.metadata["primary_candidate_asset_id"] = state.new_asset_id
        state.candidate_assets = candidate_assets
        state.candidate_output = {
            "assets": state.candidate_assets,
            "output_assets": state.candidate_assets,
            "status": "candidate_pending",
        }
        state = self._hooks.ensure_candidate_quality(identity, active, state)
        state.candidate_assets = WorkflowAssetLibraryIngestService(
            self._settings.media_data_dir
        ).ingest_ready_assets(
            workflow_id=identity.workflow_id,
            node_id=identity.node_id,
            node_type=identity.node_type,
            item_id=state.target_entity_id or request.target_entity_id or "",
            assets=state.candidate_assets,
            version_id=state.revision_id,
            workflow_selection_state="candidate",
        )
        state.candidate_output = {
            "assets": state.candidate_assets,
            "output_assets": state.candidate_assets,
            "status": "candidate_pending",
        }
        state.status = "completed"
        state.generation_status = "completed"
        state.acceptance_status = "pending"
        state.visibility_status = "visible"
        state.finished_at = utc_now().isoformat()
        self._hooks.write_state(state)
        self._hooks.sync_history_candidate_status(state)
        self._hooks.enforce_visible_candidate_limit(state)
        self._hooks.append_event(
            state,
            "revision_candidate_created",
            {
                "previous_active_asset_id": state.previous_active_asset_id,
                "previous_active_asset_ids": state.previous_active_asset_ids,
                "new_asset_id": state.new_asset_id,
                "candidate_asset_ids": candidate_asset_ids,
            },
        )
        self._hooks.emit_revision_status_changed(state)
        self._hooks.emit_candidate_created(state)
        if revision_has_quality_fields(state):
            self._hooks.emit_candidate_quality_updated(state)
        self._hooks.emit_asset_history_updated(state)
        self._hooks.emit_node_candidate_summary_updated(state)
        return state
