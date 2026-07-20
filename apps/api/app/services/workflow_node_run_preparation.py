from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.schemas.workflow_nodes import WorkflowNodeRunRequest, WorkflowNodeRunResponse
from app.services.asset_library import AssetLibraryError
from app.services.asset_library_references import (
    normalize_asset_references,
    reference_context_for_node,
)
from app.services.output_assets import dedupe_output_assets
from app.services.workflow_graph import load_graph
from app.services.workflow_input_resolver import (
    WorkflowInputResolutionError,
    WorkflowNodeInputResolver,
)
from app.services.workflow_node_asset_derivation import _trace_asset_reference_usage
from app.services.workflow_node_catalog import NODE_CATALOG
from app.services.workflow_node_errors import WorkflowNodeInputError
from app.services.workflow_node_identity import resolve_node_identity
from app.services.workflow_state import load_active_node_results


class WorkflowNodeRunPreparationMixin:
    def _validate_supported_node_type(self, node_type: str) -> None:
        if node_type not in {node.node_type for node in NODE_CATALOG}:
            raise WorkflowNodeInputError(f"unsupported node_type: {node_type}")

    def _resolve_run_request_inputs(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        settings: Settings,
    ) -> WorkflowNodeRunRequest:
        if request.auto_resolve and request.workflow_id:
            request = self._apply_auto_resolve(request, settings)
        if _has_request_asset_references(request) and request.revision is None:
            request = self._apply_request_asset_references(request, workflow_id, settings)
        return request

    def _should_skip_existing_result(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        node_type: str,
        existing_result: WorkflowNodeRunResponse | None,
    ) -> bool:
        if (
            existing_result is None
            or request.force_rerun
            or request.optimize_only
            or _has_request_asset_references(request)
        ):
            return False
        return self._result_store.existing_result_is_terminal(
            existing_result,
            node_type,
        ) and not self._result_store.latest_run_is_optimize_only(
            workflow_id,
            existing_result.node_id,
            existing_result.node_run_id,
        )

    def _with_resolved_identity(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        settings: Settings,
    ) -> WorkflowNodeRunRequest:
        identity = resolve_node_identity(
            data_dir=settings.media_data_dir,
            workflow_id=workflow_id,
            node_id=request.node_id,
            node_type=request.node_type,
        )
        return request.model_copy(
            update={
                "workflow_id": workflow_id,
                "node_id": identity.node_id,
                "node_type": identity.node_type,
            }
        )

    def _apply_auto_resolve(
        self,
        request: WorkflowNodeRunRequest,
        settings: Settings,
    ) -> WorkflowNodeRunRequest:
        try:
            resolved = WorkflowNodeInputResolver(settings).resolve_node_inputs(
                request.workflow_id or "", _request_node_id(request)
            )
        except WorkflowInputResolutionError:
            return _apply_active_result_auto_resolve(request, settings)
        merged_context: dict[str, Any] = dict(resolved.resolved_input_context)
        _merge_missing_context(merged_context, request.input_context)
        merged_assets: list[dict[str, Any]] = list(resolved.resolved_input_assets)
        seen = {str(asset.get("asset_id") or "") for asset in merged_assets}
        for asset in request.input_assets:
            asset_id = str(asset.get("asset_id") or "")
            if not asset_id or asset_id not in seen:
                merged_assets.append(asset)
                if asset_id:
                    seen.add(asset_id)
        return request.model_copy(
            update={
                "input_context": merged_context,
                "input_assets": merged_assets,
            }
        )

    def _apply_request_asset_references(
        self,
        request: WorkflowNodeRunRequest,
        workflow_id: str,
        settings: Settings,
    ) -> WorkflowNodeRunRequest:
        references = normalize_asset_references(
            settings.media_data_dir,
            _asset_references_with_request_mode(
                request.asset_references,
                request.reference_mode,
            ),
            library_entity_ids=request.library_entity_ids,
            available_node_ids=_available_reference_node_ids(
                settings.media_data_dir,
                workflow_id,
            ),
            workflow_id=workflow_id,
        )
        target_node_id = _request_node_id(request)
        reference_context = reference_context_for_node(references, target_node_id)
        if references and not reference_context["asset_references"]:
            raise AssetLibraryError("asset_reference_target_node_mismatch", 422)
        if request.save_outputs:
            _trace_asset_reference_usage(
                settings,
                workflow_id,
                target_node_id,
                reference_context["asset_references"],
            )
        merged_context = dict(request.input_context)
        for key in (
            "asset_references",
            "prompt_context_assets",
            "provider_reference_assets",
            "display_input_assets",
        ):
            merged_context[key] = reference_context[key]
        existing_mappings = [
            mapping
            for mapping in merged_context.get("source_mappings", [])
            if isinstance(mapping, dict)
            and mapping.get("source_type") not in {"asset_library", "canvas_asset"}
        ]
        merged_context["source_mappings"] = [
            *existing_mappings,
            *reference_context["source_mappings"],
        ]
        resolved_context = dict(merged_context.get("resolved_input_context") or {})
        for key in (
            "asset_references",
            "prompt_context_assets",
            "provider_reference_assets",
            "display_input_assets",
        ):
            resolved_context[key] = reference_context[key]
        merged_context["resolved_input_context"] = resolved_context
        non_library_assets = [
            asset for asset in request.input_assets if not _is_asset_reference_asset(asset)
        ]
        merged_assets = dedupe_output_assets(
            [*non_library_assets, *reference_context["display_input_assets"]]
        )
        return request.model_copy(
            update={
                "input_context": merged_context,
                "input_assets": merged_assets,
            }
        )

    def _effective_settings(self, request: WorkflowNodeRunRequest) -> Settings:
        updates: dict[str, Any] = {}
        if request.mode == "mock":
            updates["agno_mock_mode"] = True
        elif request.mode == "real":
            updates["agno_mock_mode"] = False
        if request.media_mode is not None:
            updates["media_mode"] = request.media_mode
        return replace(self._settings, **updates) if updates else self._settings

    def _validate_required_inputs(self, node_type: str, context: dict[str, Any]) -> None:
        catalog_item = next(node for node in NODE_CATALOG if node.node_type == node_type)
        for field_name in catalog_item.required_inputs:
            if node_type == "final-composition" and field_name == "segments":
                continue
            if field_name == "segments" and (
                context.get("segments") or context.get("storyboard_video", {}).get("segments")
            ):
                continue
            if field_name not in context or context[field_name] in (None, {}, []):
                raise WorkflowNodeInputError(f"missing required input: {field_name}")


def _asset_references_with_request_mode(
    asset_references: list[Any],
    reference_mode: str | None,
) -> list[dict[str, Any]]:
    normalized = []
    for reference in asset_references:
        if hasattr(reference, "model_dump"):
            payload = reference.model_dump(mode="json")
        elif isinstance(reference, dict):
            payload = dict(reference)
        else:
            payload = {"entity_id": str(reference)}
        if reference_mode and not payload.get("reference_mode"):
            payload["reference_mode"] = reference_mode
        normalized.append(payload)
    return normalized


def _apply_active_result_auto_resolve(
    request: WorkflowNodeRunRequest,
    settings: Settings,
) -> WorkflowNodeRunRequest:
    workflow_id = request.workflow_id or ""
    if not workflow_id:
        return request
    active = load_active_node_results(settings.media_data_dir, workflow_id)
    if not active:
        return request
    node_type = _request_node_type(request)
    fallback_context = _active_result_context_for_node(node_type, active)
    if not fallback_context:
        return request
    merged_context = dict(fallback_context)
    _merge_missing_context(merged_context, request.input_context)
    merged_assets = _merge_input_assets_for_auto_resolve(
        _active_result_assets_for_node(node_type, active),
        list(request.input_assets),
    )
    return request.model_copy(
        update={
            "input_context": merged_context,
            "input_assets": merged_assets,
        }
    )


def _active_result_context_for_node(
    node_type: str,
    active: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if node_type == "storyboard":
        return {
            "script": _active_output(active, "script"),
            "product_generation": _active_output(active, "product-generation"),
            "character_generation": _active_output(active, "character-generation"),
            "scene_generation": _active_output(active, "scene-generation"),
        }
    if node_type == "storyboard-video-generation":
        return {
            "storyboard": _active_output(active, "storyboard"),
            "script": _active_output(active, "script"),
            "product_generation": _active_output(active, "product-generation"),
            "character_generation": _active_output(active, "character-generation"),
            "scene_generation": _active_output(active, "scene-generation"),
            "duration_seconds": _active_script_duration(active),
        }
    if node_type == "bgm":
        return {
            "script": _active_output(active, "script"),
            "storyboard": _active_output(active, "storyboard"),
        }
    return {}


def _active_result_assets_for_node(
    node_type: str,
    active: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    upstream_map = {
        "storyboard": ["product-generation", "character-generation", "scene-generation"],
        "storyboard-video-generation": [
            "product-generation",
            "character-generation",
            "scene-generation",
            "storyboard",
        ],
        "bgm": ["storyboard"],
    }
    assets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for upstream in upstream_map.get(node_type, []):
        payload = active.get(upstream, {})
        for asset in _active_payload_assets(payload):
            asset_id = str(asset.get("asset_id") or asset.get("local_path") or "")
            if asset_id and asset_id in seen:
                continue
            assets.append(asset)
            if asset_id:
                seen.add(asset_id)
    return assets


def _active_payload_assets(payload: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for key in ("output_assets", "input_assets"):
        value = payload.get(key)
        if isinstance(value, list):
            assets.extend(asset for asset in value if isinstance(asset, dict))
    output = payload.get("output")
    if isinstance(output, dict):
        for key in ("assets", "output_assets", "segments"):
            value = output.get(key)
            if isinstance(value, list):
                assets.extend(asset for asset in value if isinstance(asset, dict))
    return assets


def _merge_input_assets_for_auto_resolve(
    resolved_assets: list[dict[str, Any]],
    request_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for asset in [*resolved_assets, *request_assets]:
        if not isinstance(asset, dict):
            continue
        asset_id = str(asset.get("asset_id") or asset.get("local_path") or "")
        if asset_id and asset_id in seen:
            continue
        merged.append(asset)
        if asset_id:
            seen.add(asset_id)
    return merged


def _active_output(active: dict[str, dict[str, Any]], node_id: str) -> dict[str, Any]:
    payload = active.get(node_id)
    output = payload.get("output") if isinstance(payload, dict) else None
    return output if isinstance(output, dict) else {}


def _active_script_duration(active: dict[str, dict[str, Any]]) -> int:
    script = _active_output(active, "script")
    try:
        return int(script.get("duration_seconds") or 30)
    except (TypeError, ValueError):
        return 30


def _merge_missing_context(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key, value in incoming.items():
        if key in target and target[key] not in (None, "", {}, []):
            continue
        if value not in (None, "", {}, []):
            target[key] = value


def _has_request_asset_references(request: WorkflowNodeRunRequest) -> bool:
    return bool(request.asset_references or request.library_entity_ids)


def _request_node_id(request: WorkflowNodeRunRequest) -> str:
    return str(request.node_id or request.node_type or "")


def _request_node_type(request: WorkflowNodeRunRequest) -> str:
    return str(request.node_type or request.node_id or "")


def _available_reference_node_ids(data_dir: Path, workflow_id: str) -> set[str]:
    graph = load_graph(data_dir, workflow_id) if workflow_id else None
    if graph is not None:
        return {node.id for node in graph.nodes}
    return {node.node_type for node in NODE_CATALOG}


def _is_asset_reference_asset(asset: Any) -> bool:
    return isinstance(asset, dict) and (
        asset.get("source_type") in {"asset_library", "canvas_asset"}
        or asset.get("source_node_id") in {"asset_library", "canvas_asset"}
        or asset.get("source") in {"asset_library", "canvas_asset"}
    )


def _is_asset_library_reference_asset(asset: Any) -> bool:
    return _is_asset_reference_asset(asset)
