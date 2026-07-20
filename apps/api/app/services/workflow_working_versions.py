from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.schemas.workflow_nodes import WorkflowNodeRunResponse
from app.schemas.workflow_working_versions import (
    WorkflowAddItemRequest,
    WorkflowAssetMutationResponse,
    WorkflowAssetPromptUpdateRequest,
    WorkflowAssetRegenerateRequest,
    WorkflowAssetSlotHistoryResponse,
    WorkflowAssetUseCurrentVersionRequest,
    WorkflowBatchUseCurrentVersionsRequest,
    WorkflowBatchUseCurrentVersionsResponse,
    WorkflowItemMutationResponse,
    WorkflowItemRegenerateRequest,
    WorkflowShotVideoBatchResponse,
    WorkflowShotVideoGenerateRequest,
    WorkflowUseCurrentVersionRequest,
    WorkflowUseShotVideosForCompositionRequest,
)
from app.services.canvas_runtime_events import CanvasRuntimeEventService
from app.services.workflow_asset_history import load_node_asset_history, write_node_asset_history
from app.services.workflow_asset_library_ingest import WorkflowAssetLibraryIngestService
from app.services.workflow_asset_prompts import asset_slot_id
from app.services.workflow_graph import load_graph
from app.services.workflow_item_prompt_utils import (
    item_id_from_payload,
    item_prompt_from_payload,
    update_item_prompt_in_payload,
)
from app.services import workflow_working_version_apply as wv_apply
from app.services import workflow_working_version_enrichment as wv_enrichment
from app.services import workflow_working_version_events as wv_events
from app.services import workflow_working_version_items as wv_items
from app.services import workflow_working_version_mutations as wv_mutations
from app.services import workflow_working_version_shot_videos as wv_shot_videos
from app.services import workflow_working_version_store as wv_store


SUPPORTED_WORKING_VERSION_NODES = {
    "product-generation",
    "character-generation",
    "scene-generation",
    "storyboard",
    "storyboard-video-generation",
}

ADD_ITEM_SUPPORTED_NODES = SUPPORTED_WORKING_VERSION_NODES
ADD_ITEM_UNSUPPORTED_NODES = {"script", "bgm", "final-composition"}


class WorkflowWorkingVersionError(ValueError):
    def __init__(self, *, status_code: int, detail: dict[str, Any]) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(
            str(detail.get("message") or detail.get("code") or "working version error")
        )


class WorkflowWorkingVersionService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._events = CanvasRuntimeEventService(settings.media_data_dir)

    def enrich_node_response(self, result: WorkflowNodeRunResponse) -> WorkflowNodeRunResponse:
        if result.node_type not in SUPPORTED_WORKING_VERSION_NODES:
            return result
        output = self.enrich_output(
            result.workflow_id,
            result.node_id,
            result.node_type,
            result.output,
            result.output_assets,
        )
        return result.model_copy(update={"output": output})

    def enrich_output(
        self,
        workflow_id: str,
        node_id: str,
        node_type: str,
        output: dict[str, Any],
        output_assets: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if node_type not in SUPPORTED_WORKING_VERSION_NODES:
            return output
        return wv_enrichment.enrich_output(
            self._settings.media_data_dir,
            workflow_id,
            node_id,
            node_type,
            output,
            output_assets,
        )

    def add_item(
        self,
        workflow_id: str,
        node_id: str,
        request: WorkflowAddItemRequest,
    ) -> WorkflowItemMutationResponse:
        graph = self._require_graph(workflow_id)
        node = wv_store.find_graph_node(graph, node_id)
        if node is None:
            raise _error(404, "target_node_not_found", f"Workflow node not found: {node_id}.")
        if (
            node.node_type in ADD_ITEM_UNSUPPORTED_NODES
            or node.node_type not in ADD_ITEM_SUPPORTED_NODES
        ):
            raise _error(
                422,
                "add_item_unsupported_node",
                f"Add item is not supported for node: {node.node_type}.",
            )
        prompt = request.prompt.strip()
        if not prompt:
            raise _error(422, "add_item_prompt_missing", "Add-item prompt must not be empty.")
        try:
            output, item = wv_mutations.add_item_to_output(
                node.output or {},
                node_type=node.node_type,
                item_type=request.item_type,
                prompt=prompt,
                insert_mode=request.insert.mode,
                relative_item_id=request.insert.relative_item_id,
                metadata=request.metadata,
            )
        except ValueError as exc:
            raise _error(422, "add_item_invalid_insert_target", str(exc)) from exc
        item_id = wv_items.require_item(output, item["item_id"])["item_id"]
        wv_store.persist_node_output(
            self._settings.media_data_dir, workflow_id, node_id, output, list(node.output_assets)
        )
        wv_store.save_graph_node_output(
            self._settings.media_data_dir, workflow_id, node_id, output, list(node.output_assets)
        )
        self._events.append_event(
            workflow_id,
            "item_added",
            node_id=node_id,
            node_type=node.node_type,
            resource_type="item",
            resource_id=item_id,
            payload={
                "workflow_id": workflow_id,
                "node_id": node_id,
                "node_type": node.node_type,
                "item_id": item_id,
                "refresh": ["workflow_nodes", "workflow_graph"],
            },
        )
        if request.run_after_apply:
            asset = wv_store.create_working_version(
                self._settings.media_data_dir,
                self._events,
                workflow_id=workflow_id,
                node_id=node_id,
                node_type=node.node_type,
                item=item,
                prompt=prompt,
            )
            self._ingest_ready_assets(
                workflow_id=workflow_id,
                node_id=node_id,
                node_type=node.node_type,
                item_id=item_id,
                assets=[asset],
                version_id=str(asset.get("run_id") or ""),
                workflow_selection_state="candidate",
            )
        enriched = self.enrich_output(
            workflow_id, node_id, node.node_type, output, node.output_assets
        )
        item = self._require_item(enriched, item_id)
        return WorkflowItemMutationResponse(
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node.node_type,
            item=item,
            followup_suggestions=wv_events.followups_for_item_action(
                node.node_type, item_id, "item_added"
            ),
        )

    def remove_item(
        self,
        workflow_id: str,
        node_id: str,
        item_id: str,
    ) -> WorkflowItemMutationResponse:
        graph = self._require_graph(workflow_id)
        node = wv_store.find_graph_node(graph, node_id)
        if node is None:
            raise _error(404, "target_node_not_found", f"Workflow node not found: {node_id}.")
        output = self.enrich_output(
            workflow_id, node_id, node.node_type, node.output, node.output_assets
        )
        item = self._require_item(output, item_id)
        if item.get("lifecycle_state") != "draft":
            raise _error(
                409,
                "active_item_remove_unsupported",
                "Only draft items can be removed in this phase.",
            )
        item = wv_mutations.archive_draft_item(output, item_id)
        wv_store.persist_node_output(
            self._settings.media_data_dir, workflow_id, node_id, output, list(node.output_assets)
        )
        wv_store.save_graph_node_output(
            self._settings.media_data_dir, workflow_id, node_id, output, list(node.output_assets)
        )
        self._events.append_event(
            workflow_id,
            "item_archived",
            node_id=node_id,
            node_type=node.node_type,
            resource_type="item",
            resource_id=item_id,
            payload={
                "workflow_id": workflow_id,
                "node_id": node_id,
                "node_type": node.node_type,
                "item_id": item_id,
                "refresh": ["workflow_nodes", "workflow_graph"],
            },
        )
        return WorkflowItemMutationResponse(
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node.node_type,
            item=item,
        )

    def update_asset_prompt(
        self,
        workflow_id: str,
        node_id: str,
        item_id: str,
        asset_id: str,
        request: WorkflowAssetPromptUpdateRequest,
    ) -> WorkflowAssetMutationResponse:
        graph = self._require_graph(workflow_id)
        node = wv_store.find_graph_node(graph, node_id)
        if node is None:
            raise _error(404, "target_node_not_found", f"Workflow node not found: {node_id}.")
        if node.node_type not in SUPPORTED_WORKING_VERSION_NODES:
            raise _error(
                422,
                "asset_prompt_unsupported_node",
                f"Asset prompts are not supported for node: {node.node_type}.",
            )
        prompt = request.prompt.strip()
        if not prompt:
            raise _error(
                422,
                "asset_prompt_missing",
                "Asset prompt must not be empty.",
            )
        output = self.enrich_output(
            workflow_id, node_id, node.node_type, node.output, node.output_assets
        )
        item = self._require_item(output, item_id)
        target = _require_asset_prompt(item, asset_id)
        resolved_slot_id = str(target.get("asset_slot_id") or asset_id)
        if request.asset_slot_id and request.asset_slot_id != resolved_slot_id:
            raise _error(
                422,
                "asset_slot_mismatch",
                "Requested asset_slot_id does not match the resolved asset target.",
            )
        if request.semantic_type and request.semantic_type != target.get("semantic_type"):
            raise _error(
                422,
                "asset_semantic_type_mismatch",
                "Requested semantic_type does not match the resolved asset target.",
            )
        history = load_node_asset_history(self._settings.media_data_dir, workflow_id, node_id)
        if not history:
            history = [dict(asset) for asset in node.output_assets]
        matched = False
        for asset in history:
            if str(asset.get("asset_id") or "") != asset_id:
                continue
            matched = True
            _apply_asset_prompt_update(
                asset,
                prompt=prompt,
                asset_slot_id=resolved_slot_id,
                mark_stale=request.mark_stale,
            )
        if not matched:
            raise _error(404, "asset_target_not_found", f"Asset not found: {asset_id}.")
        write_node_asset_history(self._settings.media_data_dir, workflow_id, node_id, history)
        output = _updated_output_with_asset_prompt(
            output,
            asset_id=asset_id,
            prompt=prompt,
            slot_id=resolved_slot_id,
            mark_stale=request.mark_stale,
        )
        output_assets = _updated_assets_with_asset_prompt(
            list(node.output_assets),
            asset_id=asset_id,
            prompt=prompt,
            slot_id=resolved_slot_id,
            mark_stale=request.mark_stale,
        )
        wv_store.persist_node_output(
            self._settings.media_data_dir, workflow_id, node_id, output, output_assets
        )
        wv_store.save_graph_node_output(
            self._settings.media_data_dir, workflow_id, node_id, output, output_assets
        )
        enriched = self.enrich_output(workflow_id, node_id, node.node_type, output, output_assets)
        item = self._require_item(enriched, item_id)
        asset = _require_asset_prompt(item, asset_id)
        self._events.append_event(
            workflow_id,
            "asset_prompt_updated",
            node_id=node_id,
            node_type=node.node_type,
            resource_type="asset",
            resource_id=asset_id,
            payload={
                "workflow_id": workflow_id,
                "node_id": node_id,
                "node_type": node.node_type,
                "item_id": item_id,
                "asset_id": asset_id,
                "asset_slot_id": resolved_slot_id,
                "refresh": ["workflow_nodes", "workflow_graph"],
            },
        )
        return WorkflowAssetMutationResponse(
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node.node_type,
            item=item,
            asset=asset,
        )

    def regenerate_asset(
        self,
        workflow_id: str,
        node_id: str,
        item_id: str,
        asset_id: str,
        request: WorkflowAssetRegenerateRequest,
    ) -> WorkflowAssetMutationResponse:
        graph = self._require_graph(workflow_id)
        node = wv_store.find_graph_node(graph, node_id)
        if node is None:
            raise _error(404, "target_node_not_found", f"Workflow node not found: {node_id}.")
        output = self.enrich_output(
            workflow_id, node_id, node.node_type, node.output, node.output_assets
        )
        item = self._require_item(output, item_id)
        target = _require_asset_prompt(item, asset_id)
        resolved_slot_id = str(target.get("asset_slot_id") or asset_id)
        if request.asset_slot_id and request.asset_slot_id != resolved_slot_id:
            raise _error(
                422,
                "asset_slot_mismatch",
                "Requested asset_slot_id does not match the resolved asset target.",
            )
        prompt = (request.prompt or target.get("prompt") or request.instruction or "").strip()
        if not prompt:
            raise _error(
                422,
                "asset_prompt_missing",
                "Asset regeneration requires a target asset prompt.",
            )
        if request.prompt:
            self.update_asset_prompt(
                workflow_id,
                node_id,
                item_id,
                asset_id,
                WorkflowAssetPromptUpdateRequest(
                    prompt=prompt,
                    asset_slot_id=resolved_slot_id,
                    semantic_type=request.semantic_type,
                    mark_stale=True,
                ),
            )
            output = self.enrich_output(
                workflow_id, node_id, node.node_type, node.output, node.output_assets
            )
            item = self._require_item(output, item_id)
            target = _require_asset_prompt(item, asset_id)
        self._events.append_event(
            workflow_id,
            "asset_working_version_started",
            node_id=node_id,
            node_type=node.node_type,
            resource_type="asset",
            resource_id=asset_id,
            payload={
                "workflow_id": workflow_id,
                "node_id": node_id,
                "node_type": node.node_type,
                "item_id": item_id,
                "asset_id": asset_id,
                "asset_slot_id": resolved_slot_id,
                "refresh": ["workflow_nodes"],
            },
        )
        generated = wv_store.create_working_version(
            self._settings.media_data_dir,
            self._events,
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node.node_type,
            item=item,
            prompt=prompt,
            visual_assets=[],
            media_type=target.get("media_type") if target.get("media_type") else None,
            asset_slot_id=resolved_slot_id,
            semantic_type=request.semantic_type or str(target.get("semantic_type") or ""),
            source_asset_id=asset_id,
        )
        self._ingest_ready_assets(
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node.node_type,
            item_id=item_id,
            assets=[generated],
            version_id=str(generated.get("run_id") or ""),
            workflow_selection_state="candidate",
        )
        self._events.append_event(
            workflow_id,
            "asset_working_version_ready",
            node_id=node_id,
            node_type=node.node_type,
            resource_type="asset",
            resource_id=asset_id,
            payload={
                "workflow_id": workflow_id,
                "node_id": node_id,
                "node_type": node.node_type,
                "item_id": item_id,
                "asset_id": asset_id,
                "asset_slot_id": resolved_slot_id,
                "version_id": generated.get("run_id"),
                "generated_asset_id": generated.get("asset_id"),
                "refresh": ["workflow_nodes", "asset_history"],
            },
        )
        output = self.enrich_output(
            workflow_id, node_id, node.node_type, node.output, node.output_assets
        )
        item = self._require_item(output, item_id)
        asset = _require_asset_prompt(item, asset_id)
        return WorkflowAssetMutationResponse(
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node.node_type,
            item=item,
            asset=asset,
        )

    def use_current_asset_version(
        self,
        workflow_id: str,
        node_id: str,
        item_id: str,
        asset_id: str,
        request: WorkflowAssetUseCurrentVersionRequest,
    ) -> WorkflowAssetMutationResponse:
        graph = self._require_graph(workflow_id)
        node = wv_store.find_graph_node(graph, node_id)
        if node is None:
            raise _error(404, "target_node_not_found", f"Workflow node not found: {node_id}.")
        output = self.enrich_output(
            workflow_id, node_id, node.node_type, node.output, node.output_assets
        )
        item = self._require_item(output, item_id)
        target = _require_asset_prompt(item, asset_id)
        resolved_slot_id = str(target.get("asset_slot_id") or asset_id)
        if request.asset_slot_id and request.asset_slot_id != resolved_slot_id:
            raise _error(
                422,
                "asset_slot_mismatch",
                "Requested asset_slot_id does not match the resolved asset target.",
            )
        current = target.get("current_working_version")
        if not isinstance(current, dict):
            raise _error(409, "working_version_missing", "Current working version is missing.")
        _validate_asset_current_version(current, request)
        selected_assets = _select_current_asset_slot(
            self._settings.media_data_dir,
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node.node_type,
            item_id=item_id,
            slot_id=resolved_slot_id,
            version=current,
            force_quality_override=request.force_use_current_version or request.quality_override,
            use_for_composition=request.use_for_composition,
        )
        self._ingest_ready_assets(
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node.node_type,
            item_id=item_id,
            assets=selected_assets,
            version_id=str(current.get("version_id") or ""),
            workflow_selection_state="used",
        )
        output = self.enrich_output(
            workflow_id, node_id, node.node_type, node.output, node.output_assets
        )
        if selected_assets:
            item = self._require_item(output, item_id)
            if _slot_updates_primary_item_uri(node.node_type, resolved_slot_id, selected_assets[0]):
                wv_items.set_item_uri(item, node.node_type, wv_items.asset_uri(selected_assets[0]))
        output_assets = wv_items.active_assets_for_output(
            load_node_asset_history(self._settings.media_data_dir, workflow_id, node_id)
        )
        output["assets"] = output_assets
        output["output_assets"] = output_assets
        wv_store.persist_node_output(
            self._settings.media_data_dir, workflow_id, node_id, output, output_assets
        )
        wv_store.save_graph_node_output(
            self._settings.media_data_dir, workflow_id, node_id, output, output_assets
        )
        affected = wv_store.mark_downstream_stale(
            self._settings.media_data_dir,
            workflow_id,
            node_id,
            changed_item_ids=[item_id],
        )
        enriched = self.enrich_output(workflow_id, node_id, node.node_type, output, output_assets)
        item = self._require_item(enriched, item_id)
        asset = _require_asset_prompt(item, asset_id)
        self._events.append_event(
            workflow_id,
            "asset_selected_version_updated",
            node_id=node_id,
            node_type=node.node_type,
            resource_type="asset",
            resource_id=asset_id,
            payload={
                "workflow_id": workflow_id,
                "node_id": node_id,
                "node_type": node.node_type,
                "item_id": item_id,
                "asset_id": asset_id,
                "asset_slot_id": resolved_slot_id,
                "version_id": current.get("version_id"),
                "affected_downstream_node_ids": affected,
                "refresh": ["workflow_nodes", "workflow_graph", "resolved_inputs"],
            },
        )
        self._events.append_event(
            workflow_id,
            "asset_history_updated",
            node_id=node_id,
            node_type=node.node_type,
            resource_type="asset",
            resource_id=asset_id,
            payload={
                "workflow_id": workflow_id,
                "node_id": node_id,
                "node_type": node.node_type,
                "item_id": item_id,
                "asset_id": asset_id,
                "asset_slot_id": resolved_slot_id,
                "refresh": ["workflow_nodes", "asset_history"],
            },
        )
        return WorkflowAssetMutationResponse(
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node.node_type,
            item=item,
            asset=asset,
            affected_downstream_node_ids=affected,
        )

    def asset_slot_history(
        self,
        workflow_id: str,
        node_id: str,
        item_id: str,
        asset_id: str,
    ) -> WorkflowAssetSlotHistoryResponse:
        graph = self._require_graph(workflow_id)
        node = wv_store.find_graph_node(graph, node_id)
        if node is None:
            raise _error(404, "target_node_not_found", f"Workflow node not found: {node_id}.")
        output = self.enrich_output(
            workflow_id, node_id, node.node_type, node.output, node.output_assets
        )
        item = self._require_item(output, item_id)
        target = _require_asset_prompt(item, asset_id)
        history_versions = list(target.get("history_versions") or [])
        for key in ("selected_version", "current_working_version"):
            version = target.get(key)
            if isinstance(version, dict) and version not in history_versions:
                history_versions.append(version)
        return WorkflowAssetSlotHistoryResponse(
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node.node_type,
            item_id=item_id,
            asset_id=asset_id,
            asset_slot_id=str(target.get("asset_slot_id") or asset_id),
            history_versions=history_versions,
        )

    def regenerate_item(
        self,
        workflow_id: str,
        node_id: str,
        item_id: str,
        request: WorkflowItemRegenerateRequest,
    ) -> WorkflowItemMutationResponse:
        for field in (
            "apply_as_current",
            "regenerate_and_use",
            "auto_accept",
            "run_downstream",
        ):
            if bool(getattr(request, field)):
                raise _error(
                    422,
                    "item_regenerate_selection_not_supported",
                    "Item regeneration does not support implicit workflow selection.",
                    field=field,
                )
        graph = self._require_graph(workflow_id)
        node = wv_store.find_graph_node(graph, node_id)
        if node is None:
            raise _error(404, "target_node_not_found", f"Workflow node not found: {node_id}.")
        if node.node_type not in {"character-generation", "scene-generation"}:
            raise _error(
                422,
                "item_regenerate_unsupported_node",
                f"Item regeneration is not supported for node: {node.node_type}.",
            )
        output = self.enrich_output(
            workflow_id, node_id, node.node_type, node.output, node.output_assets
        )
        item = self._require_item(output, item_id)
        semantic_type = request.semantic_type or wv_items.semantic_type_for_node(node.node_type)
        prompt = (request.prompt or item.get("prompt") or item_prompt_from_payload(item)).strip()
        if not prompt:
            raise _error(
                422,
                "item_regenerate_prompt_missing",
                "Item regeneration requires a target item prompt.",
            )
        if request.prompt and request.prompt.strip():
            update_item_prompt_in_payload(
                output,
                item_id=item_id,
                prompt=prompt,
                node_type=node.node_type,
                semantic_type=semantic_type,
                mark_stale=False,
            )
            wv_store.persist_node_output(
                self._settings.media_data_dir,
                workflow_id,
                node_id,
                output,
                list(node.output_assets),
            )
            wv_store.save_graph_node_output(
                self._settings.media_data_dir,
                workflow_id,
                node_id,
                output,
                list(node.output_assets),
            )
            output = self.enrich_output(
                workflow_id, node_id, node.node_type, output, node.output_assets
            )
            item = self._require_item(output, item_id)
        asset = wv_store.create_working_version(
            self._settings.media_data_dir,
            self._events,
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node.node_type,
            item=item,
            prompt=prompt,
            visual_assets=[],
            semantic_type=semantic_type,
        )
        self._ingest_ready_assets(
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node.node_type,
            item_id=item_id,
            assets=[asset],
            version_id=str(asset.get("run_id") or ""),
            workflow_selection_state="candidate",
        )
        self._events.append_event(
            workflow_id,
            "item_history_updated",
            node_id=node_id,
            node_type=node.node_type,
            resource_type="item",
            resource_id=item_id,
            payload=_item_event_payload(
                workflow_id=workflow_id,
                node_id=node_id,
                node_type=node.node_type,
                item_id=item_id,
                semantic_type=semantic_type,
                revision_id=str(asset.get("run_id") or ""),
                asset_ids=[str(asset.get("asset_id") or "")],
                refresh=["workflow_nodes", "asset_history"],
            ),
        )
        self._events.append_event(
            workflow_id,
            "node_assets_updated",
            node_id=node_id,
            node_type=node.node_type,
            resource_type="node",
            resource_id=node_id,
            payload=_item_event_payload(
                workflow_id=workflow_id,
                node_id=node_id,
                node_type=node.node_type,
                item_id=item_id,
                semantic_type=semantic_type,
                revision_id=str(asset.get("run_id") or ""),
                asset_ids=[str(asset.get("asset_id") or "")],
                refresh=["workflow_nodes"],
            ),
        )
        self._events.append_event(
            workflow_id,
            "asset_reference_suggestions_updated",
            node_id=node_id,
            node_type=node.node_type,
            resource_type="asset_library",
            resource_id=item_id,
            payload=_item_event_payload(
                workflow_id=workflow_id,
                node_id=node_id,
                node_type=node.node_type,
                item_id=item_id,
                semantic_type=semantic_type,
                revision_id=str(asset.get("run_id") or ""),
                asset_ids=[str(asset.get("asset_id") or "")],
                refresh=["asset_library", "asset_reference_suggestions"],
            ),
        )
        enriched = self.enrich_output(
            workflow_id,
            node_id,
            node.node_type,
            output,
            list(node.output_assets),
        )
        item = self._require_item(enriched, item_id)
        return WorkflowItemMutationResponse(
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node.node_type,
            item=item,
            affected_downstream_node_ids=[],
            followup_suggestions=wv_events.followups_for_item_action(
                node.node_type, item_id, "item_regenerated"
            ),
        )

    def use_current_version(
        self,
        workflow_id: str,
        node_id: str,
        item_id: str,
        request: WorkflowUseCurrentVersionRequest,
    ) -> WorkflowItemMutationResponse:
        graph = self._require_graph(workflow_id)
        node = wv_store.find_graph_node(graph, node_id)
        if node is None:
            raise _error(404, "target_node_not_found", f"Workflow node not found: {node_id}.")
        output = self.enrich_output(
            workflow_id, node_id, node.node_type, node.output, node.output_assets
        )
        item = self._require_item(output, item_id)
        try:
            current = wv_apply.validate_current_version(
                item.get("current_working_version"), request
            )
            selected_assets = wv_apply.select_current_assets(
                self._settings.media_data_dir,
                workflow_id=workflow_id,
                node_id=node_id,
                node_type=node.node_type,
                item_id=item_id,
                version=current,
                request=request,
            )
            output = wv_apply.apply_selected_assets_to_output(
                self._settings.media_data_dir,
                workflow_id=workflow_id,
                node_id=node_id,
                node_type=node.node_type,
                output=output,
                item_id=item_id,
                assets=selected_assets,
                request=request,
            )
            self._ingest_ready_assets(
                workflow_id=workflow_id,
                node_id=node_id,
                node_type=node.node_type,
                item_id=item_id,
                assets=selected_assets,
                version_id=str(current.get("version_id") or ""),
                workflow_selection_state="used",
            )
        except ValueError as exc:
            self._raise_working_version_apply_error(exc)
        output_assets = wv_apply.active_output_assets(
            self._settings.media_data_dir, workflow_id, node_id
        )
        wv_store.persist_node_output(
            self._settings.media_data_dir, workflow_id, node_id, output, output_assets
        )
        wv_store.save_graph_node_output(
            self._settings.media_data_dir, workflow_id, node_id, output, output_assets
        )
        affected = wv_store.mark_downstream_stale(
            self._settings.media_data_dir,
            workflow_id,
            node_id,
            changed_item_ids=[item_id],
        )
        enriched = self.enrich_output(workflow_id, node_id, node.node_type, output, output_assets)
        item = self._require_item(enriched, item_id)
        self._events.append_event(
            workflow_id,
            "item_selected_version_updated",
            node_id=node_id,
            node_type=node.node_type,
            resource_type="item",
            resource_id=item_id,
            payload={
                "workflow_id": workflow_id,
                "node_id": node_id,
                "node_type": node.node_type,
                "item_id": item_id,
                "version_id": current.get("version_id"),
                "affected_downstream_node_ids": affected,
                "refresh": ["workflow_nodes", "workflow_graph", "resolved_inputs"],
            },
        )
        self._events.append_event(
            workflow_id,
            "item_history_updated",
            node_id=node_id,
            node_type=node.node_type,
            resource_type="item",
            resource_id=item_id,
            payload={
                "workflow_id": workflow_id,
                "node_id": node_id,
                "node_type": node.node_type,
                "item_id": item_id,
                "refresh": ["workflow_nodes", "asset_history"],
            },
        )
        followups = wv_events.followups_for_item_action(node.node_type, item_id, "item_selected")
        for followup in followups:
            self._events.append_event(
                workflow_id,
                "director_followup_suggested",
                node_id=node_id,
                node_type=node.node_type,
                resource_type="item",
                resource_id=item_id,
                payload={**followup, "refresh": ["agent_conversation"]},
            )
        return WorkflowItemMutationResponse(
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node.node_type,
            item=item,
            affected_downstream_node_ids=affected,
            followup_suggestions=followups,
        )

    def batch_use_current_versions(
        self,
        workflow_id: str,
        node_id: str,
        request: WorkflowBatchUseCurrentVersionsRequest,
    ) -> WorkflowBatchUseCurrentVersionsResponse:
        graph = self._require_graph(workflow_id)
        node = wv_store.find_graph_node(graph, node_id)
        if node is None:
            raise _error(404, "target_node_not_found", f"Workflow node not found: {node_id}.")
        output = self.enrich_output(
            workflow_id, node_id, node.node_type, node.output, node.output_assets
        )
        items = wv_items.payload_items(output, node.node_type)
        try:
            target_item_ids = wv_apply.batch_target_item_ids(items, request)
        except ValueError as exc:
            raise _error(422, "batch_scope_invalid", str(exc)) from exc
        applied: list[str] = []
        failed: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        affected: list[str] = []
        for target_item_id in target_item_ids:
            try:
                response = self.use_current_version(
                    workflow_id,
                    node_id,
                    target_item_id,
                    WorkflowUseCurrentVersionRequest(
                        force_use_current_version=False,
                        use_for_composition=request.use_for_composition,
                    ),
                )
            except WorkflowWorkingVersionError as exc:
                failed.append(
                    {
                        "item_id": target_item_id,
                        "error_code": exc.detail.get("code"),
                        "message": exc.detail.get("message"),
                    }
                )
                continue
            if response.item.get("needs_apply"):
                skipped.append({"item_id": target_item_id, "reason": "not_applied"})
                continue
            applied.append(target_item_id)
            affected.extend(response.affected_downstream_node_ids)
        affected = list(dict.fromkeys(affected))
        self._events.append_event(
            workflow_id,
            "item_batch_apply_completed",
            node_id=node_id,
            node_type=node.node_type,
            resource_type="node",
            resource_id=node_id,
            payload={
                "workflow_id": workflow_id,
                "node_id": node_id,
                "applied_item_ids": applied,
                "failed_items": failed,
                "skipped_items": skipped,
                "affected_downstream_node_ids": affected,
                "refresh": ["workflow_nodes", "workflow_graph", "resolved_inputs"],
            },
        )
        return WorkflowBatchUseCurrentVersionsResponse(
            workflow_id=workflow_id,
            node_id=node_id,
            applied_item_ids=applied,
            skipped_items=skipped,
            failed_items=failed,
            affected_downstream_node_ids=affected,
        )

    def generate_shot_video(
        self,
        workflow_id: str,
        shot_id: str,
        request: WorkflowShotVideoGenerateRequest,
    ) -> WorkflowItemMutationResponse:
        try:
            shot = wv_shot_videos.resolve_storyboard_shot(
                self._settings.media_data_dir, workflow_id, shot_id
            )
        except ValueError as exc:
            raise _error(404, "target_shot_not_found", str(exc)) from exc
        visual_assets = wv_shot_videos.storyboard_visual_assets(
            self._settings.media_data_dir, workflow_id, shot_id
        )
        if request.strict_reference_mode and not visual_assets:
            raise _error(
                409,
                "shot_video_reference_required",
                "Shot video generation requires a selected storyboard image or visual reference.",
            )
        video_node_id = "storyboard-video-generation"
        graph = self._require_graph(workflow_id)
        node = wv_store.find_graph_node(graph, video_node_id)
        node_type = node.node_type if node is not None else video_node_id
        prompt = (
            request.prompt
            or item_prompt_from_payload(shot)
            or f"Generate shot video for {shot_id}."
        )
        self._events.append_event(
            workflow_id,
            "shot_video_generation_started",
            node_id=video_node_id,
            node_type=node_type,
            resource_type="shot",
            resource_id=shot_id,
            payload={
                "workflow_id": workflow_id,
                "node_id": video_node_id,
                "node_type": node_type,
                "shot_id": shot_id,
                "refresh": ["workflow_nodes"],
            },
        )
        item = wv_items.new_item_payload(
            item_id=shot_id,
            item_type="storyboard_video",
            node_type="storyboard-video-generation",
            prompt=prompt,
            order=wv_items.item_order(shot, 1),
            metadata={"source_storyboard_shot": shot_id},
        )
        output = wv_shot_videos.ensure_video_node_output(
            self._settings.media_data_dir, workflow_id, video_node_id, item
        )
        asset = wv_store.create_working_version(
            self._settings.media_data_dir,
            self._events,
            workflow_id=workflow_id,
            node_id=video_node_id,
            node_type="storyboard-video-generation",
            item=item,
            prompt=prompt,
            visual_assets=visual_assets,
            media_type="video",
        )
        self._ingest_ready_assets(
            workflow_id=workflow_id,
            node_id=video_node_id,
            node_type="storyboard-video-generation",
            item_id=shot_id,
            assets=[asset],
            version_id=str(asset.get("run_id") or ""),
            workflow_selection_state="candidate",
        )
        output = self.enrich_output(
            workflow_id, video_node_id, "storyboard-video-generation", output, []
        )
        item = self._require_item(output, shot_id)
        self._events.append_event(
            workflow_id,
            "shot_video_generation_completed",
            node_id=video_node_id,
            node_type=node_type,
            resource_type="shot",
            resource_id=shot_id,
            payload={
                "workflow_id": workflow_id,
                "node_id": video_node_id,
                "node_type": node_type,
                "shot_id": shot_id,
                "version_id": asset.get("metadata", {}).get("revision_id") or asset.get("run_id"),
                "refresh": ["workflow_nodes", "workflow_graph"],
            },
        )
        followups = wv_events.followups_for_item_action(node_type, shot_id, "shot_video_generated")
        return WorkflowItemMutationResponse(
            workflow_id=workflow_id,
            node_id=video_node_id,
            node_type=node_type,
            item=item,
            followup_suggestions=followups,
        )

    def generate_missing_stale_shot_videos(
        self,
        workflow_id: str,
    ) -> WorkflowShotVideoBatchResponse:
        shots = wv_shot_videos.storyboard_shots(self._settings.media_data_dir, workflow_id)
        statuses: list[dict[str, Any]] = []
        for shot in shots:
            shot_id = item_id_from_payload(shot)
            if not shot_id:
                continue
            video_item = wv_shot_videos.video_item(
                self._settings.media_data_dir, workflow_id, shot_id
            )
            if (
                video_item
                and not video_item.get("needs_apply")
                and video_item.get("selected_version")
            ):
                statuses.append({"shot_id": shot_id, "status": "skipped", "reason": "clean"})
                continue
            try:
                generated = self.generate_shot_video(
                    workflow_id,
                    shot_id,
                    WorkflowShotVideoGenerateRequest(
                        prompt=item_prompt_from_payload(shot), strict_reference_mode=True
                    ),
                )
            except WorkflowWorkingVersionError as exc:
                statuses.append(
                    {
                        "shot_id": shot_id,
                        "status": "failed",
                        "error_code": exc.detail.get("code"),
                        "message": exc.detail.get("message"),
                    }
                )
                continue
            statuses.append({"shot_id": shot_id, "status": "generated", "item": generated.item})
        self._events.append_event(
            workflow_id,
            "shot_video_batch_completed",
            node_id="storyboard-video-generation",
            node_type="storyboard-video-generation",
            resource_type="node",
            resource_id="storyboard-video-generation",
            payload={
                "workflow_id": workflow_id,
                "statuses": statuses,
                "refresh": ["workflow_nodes"],
            },
        )
        return WorkflowShotVideoBatchResponse(
            workflow_id=workflow_id,
            statuses=statuses,
            followup_suggestions=[
                {
                    "action_type": "use_current_shot_videos_for_composition",
                    "confirm_required": True,
                    "node_id": "storyboard-video-generation",
                }
            ],
        )

    def regenerate_all_selected_shot_videos(
        self, workflow_id: str
    ) -> WorkflowShotVideoBatchResponse:
        shots = wv_shot_videos.storyboard_shots(self._settings.media_data_dir, workflow_id)
        statuses: list[dict[str, Any]] = []
        for shot in shots:
            shot_id = item_id_from_payload(shot)
            if not shot_id:
                continue
            try:
                generated = self.generate_shot_video(
                    workflow_id,
                    shot_id,
                    WorkflowShotVideoGenerateRequest(
                        prompt=item_prompt_from_payload(shot), strict_reference_mode=True
                    ),
                )
            except WorkflowWorkingVersionError as exc:
                statuses.append(
                    {
                        "shot_id": shot_id,
                        "status": "failed",
                        "error_code": exc.detail.get("code"),
                        "message": exc.detail.get("message"),
                    }
                )
                continue
            statuses.append({"shot_id": shot_id, "status": "generated", "item": generated.item})
        self._events.append_event(
            workflow_id,
            "shot_video_batch_completed",
            node_id="storyboard-video-generation",
            node_type="storyboard-video-generation",
            resource_type="node",
            resource_id="storyboard-video-generation",
            payload={
                "workflow_id": workflow_id,
                "statuses": statuses,
                "refresh": ["workflow_nodes"],
            },
        )
        return WorkflowShotVideoBatchResponse(workflow_id=workflow_id, statuses=statuses)

    def use_current_shot_videos_for_composition(
        self,
        workflow_id: str,
        request: WorkflowUseShotVideosForCompositionRequest,
    ) -> WorkflowBatchUseCurrentVersionsResponse:
        batch = WorkflowBatchUseCurrentVersionsRequest(
            item_ids=request.shot_ids,
            scope=request.scope,
            use_for_composition=True,
        )
        response = self.batch_use_current_versions(
            workflow_id,
            "storyboard-video-generation",
            batch,
        )
        self._events.append_event(
            workflow_id,
            "shot_video_composition_selection_updated",
            node_id="storyboard-video-generation",
            node_type="storyboard-video-generation",
            resource_type="node",
            resource_id="storyboard-video-generation",
            payload={
                "workflow_id": workflow_id,
                "applied_item_ids": response.applied_item_ids,
                "refresh": ["workflow_nodes", "workflow_graph", "final_composition_timeline"],
            },
        )
        if response.applied_item_ids:
            wv_store.mark_downstream_stale(
                self._settings.media_data_dir,
                workflow_id,
                "storyboard-video-generation",
                changed_item_ids=response.applied_item_ids,
            )
        return response

    def _require_graph(self, workflow_id: str):
        graph = load_graph(self._settings.media_data_dir, workflow_id)
        if graph is None:
            raise _error(
                404, "workflow_graph_not_found", f"Workflow graph not found: {workflow_id}."
            )
        return graph

    def _require_item(self, output: dict[str, Any], item_id: str) -> dict[str, Any]:
        try:
            return wv_items.require_item(output, item_id)
        except ValueError as exc:
            raise _error(404, "target_item_not_found", str(exc)) from exc

    def _raise_working_version_apply_error(self, exc: ValueError) -> None:
        message = str(exc)
        if message.startswith("working_version_missing:"):
            raise _error(409, "working_version_missing", message.split(":", 1)[1].strip()) from exc
        if message.startswith("working_version_not_ready:"):
            raise _error(
                409, "working_version_not_ready", message.split(":", 1)[1].strip()
            ) from exc
        if message.startswith("quality_blocked:"):
            raise _error(
                409,
                "quality_blocked",
                message.split(":", 1)[1].strip(),
                quality_issues=getattr(exc, "quality_issues", []),
            ) from exc
        if "Target item not found" in message:
            raise _error(404, "target_item_not_found", message) from exc
        raise _error(409, "working_version_missing", message) from exc

    def _ingest_ready_assets(
        self,
        *,
        workflow_id: str,
        node_id: str,
        node_type: str,
        item_id: str,
        assets: list[dict[str, Any]],
        version_id: str,
        workflow_selection_state: str,
    ) -> list[dict[str, Any]]:
        return WorkflowAssetLibraryIngestService(
            self._settings.media_data_dir,
            self._events,
        ).ingest_ready_assets(
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node_type,
            item_id=item_id,
            assets=assets,
            version_id=version_id,
            workflow_selection_state=workflow_selection_state,
        )


def _error(
    status_code: int, code: str, message: str, **metadata: Any
) -> WorkflowWorkingVersionError:
    return WorkflowWorkingVersionError(
        status_code=status_code,
        detail={"code": code, "message": message, **metadata},
    )


def _require_asset_prompt(item: dict[str, Any], asset_id: str) -> dict[str, Any]:
    for asset in item.get("asset_prompts") or []:
        if isinstance(asset, dict) and str(asset.get("asset_id") or "") == asset_id:
            return asset
    raise _error(404, "asset_target_not_found", f"Asset not found: {asset_id}.")


def _apply_asset_prompt_update(
    asset: dict[str, Any],
    *,
    prompt: str,
    asset_slot_id: str,
    mark_stale: bool,
) -> None:
    asset["prompt"] = prompt
    asset["prompt_source"] = "user"
    asset["manual_prompt_dirty"] = True
    asset["asset_slot_id"] = asset_slot_id
    metadata = asset.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["asset_slot_id"] = asset_slot_id
        metadata["source_asset_prompt"] = prompt
        metadata["prompt_source"] = "user"
        metadata["manual_prompt_dirty"] = True
        if mark_stale:
            metadata["stale"] = True


def _updated_assets_with_asset_prompt(
    assets: list[dict[str, Any]],
    *,
    asset_id: str,
    prompt: str,
    slot_id: str,
    mark_stale: bool,
) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    for asset in assets:
        item = dict(asset)
        if str(item.get("asset_id") or "") == asset_id:
            _apply_asset_prompt_update(
                item,
                prompt=prompt,
                asset_slot_id=slot_id,
                mark_stale=mark_stale,
            )
        updated.append(item)
    return updated


def _updated_output_with_asset_prompt(
    output: dict[str, Any],
    *,
    asset_id: str,
    prompt: str,
    slot_id: str,
    mark_stale: bool,
) -> dict[str, Any]:
    updated = dict(output)
    for key in ("assets", "output_assets"):
        value = updated.get(key)
        if not isinstance(value, list):
            continue
        updated[key] = _updated_assets_with_asset_prompt(
            [asset for asset in value if isinstance(asset, dict)],
            asset_id=asset_id,
            prompt=prompt,
            slot_id=slot_id,
            mark_stale=mark_stale,
        )
    return updated


def _validate_asset_current_version(
    version: dict[str, Any],
    request: WorkflowAssetUseCurrentVersionRequest,
) -> None:
    if version.get("status") not in {"ready", "selected"}:
        raise _error(
            409,
            "working_version_not_ready",
            "Current working version is not ready.",
        )
    if (
        str(version.get("quality_status") or "") == "failed"
        and not request.force_use_current_version
        and not request.quality_override
        and not version.get("quality_override")
    ):
        exc = _error(
            409,
            "quality_blocked",
            "Current working version failed quality review.",
            quality_issues=version.get("quality_issues") or [],
        )
        raise exc


def _select_current_asset_slot(
    data_dir,
    *,
    workflow_id: str,
    node_id: str,
    node_type: str,
    item_id: str,
    slot_id: str,
    version: dict[str, Any],
    force_quality_override: bool,
    use_for_composition: bool,
) -> list[dict[str, Any]]:
    asset_ids = {str(asset_id) for asset_id in version.get("asset_ids", []) if asset_id}
    history = load_node_asset_history(data_dir, workflow_id, node_id)
    selected_assets: list[dict[str, Any]] = []
    from app.services.agent_trace import utc_now

    now = utc_now().isoformat()
    for asset in history:
        if not wv_items.asset_matches_item(asset, item_id, node_type):
            continue
        if asset_slot_id(asset) != slot_id:
            continue
        is_selected = str(asset.get("asset_id") or "") in asset_ids
        asset["is_active"] = is_selected
        if not is_selected:
            continue
        asset["candidate_status"] = "accepted"
        asset["acceptance_status"] = "accepted"
        asset["visibility_status"] = "visible"
        asset["selected_at"] = now
        asset["selected_reason"] = "user_override" if force_quality_override else "user_selected"
        if force_quality_override:
            asset["quality_override"] = True
            metadata = asset.setdefault("metadata", {})
            if isinstance(metadata, dict):
                metadata["quality_override"] = True
                metadata["selected_reason"] = "user_override"
        if use_for_composition:
            asset["selected_for_composition"] = True
        selected_assets.append(dict(asset))
    if not selected_assets:
        raise _error(409, "working_version_missing", "Current working version assets are missing.")
    write_node_asset_history(data_dir, workflow_id, node_id, history)
    return selected_assets


def _slot_updates_primary_item_uri(
    node_type: str,
    slot_id: str,
    asset: dict[str, Any],
) -> bool:
    default_semantic = wv_items.semantic_type_for_node(node_type)
    if str(asset.get("semantic_type") or "") == default_semantic:
        return True
    return slot_id.endswith(".main") or slot_id.endswith("_main")


def _item_event_payload(
    *,
    workflow_id: str,
    node_id: str,
    node_type: str,
    item_id: str,
    semantic_type: str,
    revision_id: str,
    asset_ids: list[str],
    refresh: list[str],
) -> dict[str, Any]:
    return {
        "workflow_id": workflow_id,
        "node_id": node_id,
        "node_type": node_type,
        "item_id": item_id,
        "semantic_type": semantic_type,
        "revision_id": revision_id,
        "asset_ids": asset_ids,
        "refresh": refresh,
    }
