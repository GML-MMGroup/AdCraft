from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.schemas.agent_conversations import NodeReference
from app.schemas.canvas_targets import CanvasTargetReference, NormalizedCanvasTarget
from app.schemas.workflow_graph import WorkflowGraph, WorkflowGraphNode
from app.services.asset_library import AssetLibraryError, AssetLibraryService
from app.services.asset_reference_sources import load_canvas_assets
from app.services.workflow_graph import WorkflowGraphError, WorkflowGraphService

USER_TARGETABLE_NODE_TYPES = {
    "script",
    "character-generation",
    "scene-generation",
    "storyboard",
    "storyboard-video-generation",
    "bgm",
    "final-composition",
}


@dataclass(frozen=True)
class CanvasTargetResolutionError:
    error_code: str
    message: str
    target_node_id: str | None = None
    target: NormalizedCanvasTarget | None = None
    metadata: dict[str, Any] | None = None

    def metadata_payload(self) -> dict[str, Any]:
        payload = dict(self.metadata or {})
        if self.target is not None:
            payload["target"] = self.target.model_dump(mode="json")
        return payload


class CanvasTargetResolverService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        data_dir: Path | None = None,
        workflow_graph_service: WorkflowGraphService | None = None,
    ) -> None:
        self._data_dir = data_dir or (settings.media_data_dir if settings else Path("data"))
        self._settings = settings or Settings(media_data_dir=self._data_dir)
        self._graph_service = workflow_graph_service or WorkflowGraphService(
            data_dir=self._data_dir
        )

    def resolve_explicit_target(
        self,
        *,
        workflow_id: str,
        target_references: list[CanvasTargetReference | dict[str, Any]],
        node_references: list[NodeReference | dict[str, Any]],
    ) -> NormalizedCanvasTarget | CanvasTargetResolutionError | None:
        target_refs = [_target_reference(reference) for reference in target_references]
        node_refs = [_node_reference(reference) for reference in node_references]
        if target_refs and len(target_refs) != 1:
            return CanvasTargetResolutionError(
                error_code="target_reference_ambiguous",
                message="Mention exactly one canvas target.",
                metadata={"matching_targets": [ref.model_dump(mode="json") for ref in target_refs]},
            )
        if (
            target_refs
            and node_refs
            and not self._legacy_node_reference_matches(target_refs[0], node_refs)
        ):
            return CanvasTargetResolutionError(
                error_code="target_reference_conflict",
                message="target_references and node_references point to different targets.",
                target_node_id=target_refs[0].node_id,
                target=self._partial_target(workflow_id, target_refs[0]),
                metadata={
                    "node_references": [
                        reference.model_dump(mode="json") for reference in node_refs
                    ],
                },
            )
        if target_refs:
            return self.resolve_target(workflow_id=workflow_id, reference=target_refs[0])
        if node_refs:
            if len(node_refs) != 1:
                return CanvasTargetResolutionError(
                    error_code="target_reference_ambiguous",
                    message="Mention exactly one canvas target.",
                    metadata={"matching_node_ids": [ref.node_id for ref in node_refs]},
                )
            return self.resolve_target(
                workflow_id=workflow_id,
                reference=CanvasTargetReference(
                    target_type="node",
                    node_id=node_refs[0].node_id,
                    node_type=node_refs[0].node_type,
                    semantic_type=node_refs[0].node_type or "workflow_node",
                    intent_scope="single",
                    mention_text=node_refs[0].mention_text,
                    source=node_refs[0].source,
                ),
            )
        return None

    def resolve_target(
        self,
        *,
        workflow_id: str,
        reference: CanvasTargetReference,
    ) -> NormalizedCanvasTarget | CanvasTargetResolutionError:
        graph = self._load_graph(workflow_id)
        if isinstance(graph, CanvasTargetResolutionError):
            return graph
        if reference.target_type == "node":
            return self._resolve_node_target(workflow_id, graph, reference)
        if reference.target_type == "item":
            return self._resolve_item_target(workflow_id, graph, reference)
        if reference.target_type == "asset":
            return self._resolve_asset_target(workflow_id, graph, reference)
        return CanvasTargetResolutionError(
            error_code="unsupported_target_type",
            message=f"Unsupported target_type: {reference.target_type}.",
            target=self._partial_target(workflow_id, reference),
        )

    def normalized_node_target(
        self,
        *,
        workflow_id: str,
        node: WorkflowGraphNode,
        source: str = "mention",
        mention_text: str | None = None,
        semantic_type: str | None = None,
    ) -> NormalizedCanvasTarget:
        return NormalizedCanvasTarget(
            workflow_id=workflow_id,
            target_type="node",
            node_id=node.id,
            node_type=node.node_type,
            semantic_type=semantic_type or "workflow_node",
            intent_scope="single",
            display_name=node.title,
            source=source,  # type: ignore[arg-type]
            metadata={},
        )

    def _resolve_node_target(
        self,
        workflow_id: str,
        graph: WorkflowGraph,
        reference: CanvasTargetReference,
    ) -> NormalizedCanvasTarget | CanvasTargetResolutionError:
        node = _find_node(graph, reference.node_id)
        if node is None:
            return CanvasTargetResolutionError(
                error_code="target_node_not_found",
                message=f"Workflow node not found: {reference.node_id}.",
                target_node_id=reference.node_id,
                target=self._partial_target(workflow_id, reference),
            )
        hidden = _hidden_node_error(workflow_id, node, reference)
        if hidden is not None:
            return hidden
        if reference.node_type and reference.node_type != node.node_type:
            return CanvasTargetResolutionError(
                error_code="target_owner_mismatch",
                message=(
                    f"Workflow node {node.id} uses node_type {node.node_type}, "
                    f"not {reference.node_type}."
                ),
                target_node_id=node.id,
                target=self._partial_target(workflow_id, reference, node=node),
                metadata={"actual_node_type": node.node_type},
            )
        return NormalizedCanvasTarget(
            workflow_id=workflow_id,
            target_type="node",
            node_id=node.id,
            node_type=node.node_type,
            semantic_type=reference.semantic_type or "workflow_node",
            intent_scope=reference.intent_scope,
            display_name=node.title,
            source=reference.source,
            metadata=dict(reference.metadata),
        )

    def _resolve_item_target(
        self,
        workflow_id: str,
        graph: WorkflowGraph,
        reference: CanvasTargetReference,
    ) -> NormalizedCanvasTarget | CanvasTargetResolutionError:
        node = _find_node(graph, reference.node_id)
        if node is None:
            return CanvasTargetResolutionError(
                error_code="target_node_not_found",
                message=f"Workflow node not found: {reference.node_id}.",
                target_node_id=reference.node_id,
                target=self._partial_target(workflow_id, reference),
            )
        hidden = _hidden_node_error(workflow_id, node, reference)
        if hidden is not None:
            return hidden
        item = _find_dynamic_item(node, reference.item_id)
        if item is None:
            return CanvasTargetResolutionError(
                error_code="target_item_not_found",
                message=f"Target item not found: {reference.item_id}.",
                target_node_id=node.id,
                target=self._partial_target(workflow_id, reference, node=node),
            )
        return NormalizedCanvasTarget(
            workflow_id=workflow_id,
            target_type="item",
            node_id=node.id,
            node_type=node.node_type,
            item_id=reference.item_id,
            semantic_type=reference.semantic_type or _item_semantic_type(node, item),
            intent_scope=reference.intent_scope,
            display_name=_item_display_name(reference.item_id, item),
            source=reference.source,
            metadata={"item": item, **dict(reference.metadata)},
        )

    def _resolve_asset_target(
        self,
        workflow_id: str,
        graph: WorkflowGraph,
        reference: CanvasTargetReference,
    ) -> NormalizedCanvasTarget | CanvasTargetResolutionError:
        asset = _find_graph_asset(graph, reference.asset_id)
        if asset is None:
            asset = _find_canvas_asset(self._data_dir, workflow_id, reference.asset_id)
        if asset is None:
            asset = _find_library_asset(self._settings, reference.asset_id)
        if asset is None:
            return CanvasTargetResolutionError(
                error_code="target_asset_not_found",
                message=f"Target asset not found: {reference.asset_id}.",
                target_node_id=reference.node_id,
                target=self._partial_target(workflow_id, reference),
            )
        asset_node_id = _first_text(
            asset.get("node_id"),
            asset.get("source_node_id"),
            asset.get("source"),
            reference.node_id,
        )
        node = _find_node(graph, asset_node_id)
        if node is None and reference.node_id:
            node = _find_node(graph, reference.node_id)
        if node is not None:
            hidden = _hidden_node_error(workflow_id, node, reference)
            if hidden is not None:
                return hidden
        if reference.node_id and asset_node_id and reference.node_id != asset_node_id:
            return CanvasTargetResolutionError(
                error_code="target_owner_mismatch",
                message=(
                    f"Asset {reference.asset_id} belongs to {asset_node_id}, "
                    f"not {reference.node_id}."
                ),
                target_node_id=reference.node_id,
                target=self._partial_target(workflow_id, reference, node=node),
                metadata={"asset_node_id": asset_node_id},
            )
        asset_item_id = _first_text(asset.get("item_id"), asset.get("entity_id"), reference.item_id)
        return NormalizedCanvasTarget(
            workflow_id=workflow_id,
            target_type="asset",
            node_id=node.id if node is not None else asset_node_id,
            node_type=node.node_type if node is not None else reference.node_type,
            item_id=asset_item_id,
            asset_id=reference.asset_id,
            semantic_type=reference.semantic_type or _first_text(asset.get("semantic_type")),
            intent_scope=reference.intent_scope,
            display_name=_first_text(
                asset.get("display_name"), asset.get("title"), reference.asset_id
            ),
            source=reference.source,
            metadata={"asset": asset, **dict(reference.metadata)},
        )

    def _legacy_node_reference_matches(
        self,
        target_reference: CanvasTargetReference,
        node_references: list[NodeReference],
    ) -> bool:
        if len(node_references) != 1:
            return False
        node_reference = node_references[0]
        return (
            target_reference.target_type == "node"
            and target_reference.node_id == node_reference.node_id
            and (
                not target_reference.node_type
                or not node_reference.node_type
                or target_reference.node_type == node_reference.node_type
            )
        )

    def _partial_target(
        self,
        workflow_id: str,
        reference: CanvasTargetReference,
        *,
        node: WorkflowGraphNode | None = None,
    ) -> NormalizedCanvasTarget:
        return NormalizedCanvasTarget(
            workflow_id=workflow_id,
            target_type=reference.target_type,
            node_id=reference.node_id or (node.id if node is not None else None),
            node_type=node.node_type if node is not None else reference.node_type,
            item_id=reference.item_id,
            asset_id=reference.asset_id,
            semantic_type=reference.semantic_type,
            intent_scope=reference.intent_scope,
            display_name=node.title if node is not None else None,
            source=reference.source,
            resolved=False,
            metadata=dict(reference.metadata),
        )

    def _load_graph(self, workflow_id: str) -> WorkflowGraph | CanvasTargetResolutionError:
        try:
            return self._graph_service.get_graph(workflow_id)
        except WorkflowGraphError:
            return CanvasTargetResolutionError(
                error_code="target_reference_not_found",
                message=f"Workflow graph not found: {workflow_id}.",
            )


def _target_reference(value: CanvasTargetReference | dict[str, Any]) -> CanvasTargetReference:
    if isinstance(value, CanvasTargetReference):
        return value
    return CanvasTargetReference.model_validate(value)


def _node_reference(value: NodeReference | dict[str, Any]) -> NodeReference:
    if isinstance(value, NodeReference):
        return value
    return NodeReference.model_validate(value)


def _find_node(graph: WorkflowGraph, node_id: str | None) -> WorkflowGraphNode | None:
    if not node_id:
        return None
    return next((node for node in graph.nodes if node.id == node_id), None)


def _hidden_node_error(
    workflow_id: str,
    node: WorkflowGraphNode,
    reference: CanvasTargetReference,
) -> CanvasTargetResolutionError | None:
    if _node_is_user_targetable(node):
        return None
    return CanvasTargetResolutionError(
        error_code="target_reference_hidden",
        message=f"Workflow node is not user-targetable: {node.id}.",
        target_node_id=node.id,
        target=NormalizedCanvasTarget(
            workflow_id=workflow_id,
            target_type=reference.target_type,
            node_id=node.id,
            node_type=node.node_type,
            item_id=reference.item_id,
            asset_id=reference.asset_id,
            semantic_type=reference.semantic_type,
            intent_scope=reference.intent_scope,
            display_name=node.title,
            source=reference.source,
            resolved=False,
            metadata=dict(reference.metadata),
        ),
    )


def _node_is_user_targetable(node: WorkflowGraphNode) -> bool:
    return bool(node.can_run_standalone) and node.node_type in USER_TARGETABLE_NODE_TYPES


def _find_dynamic_item(node: WorkflowGraphNode, item_id: str | None) -> dict[str, Any] | None:
    if not item_id:
        return None
    for item in _dynamic_items(node):
        if _item_id(item) == item_id:
            return item
    return None


def _dynamic_items(node: WorkflowGraphNode) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for value in (
        node.input_context.get("media_items"),
        node.output.get("media_items"),
        node.output.get("items"),
    ):
        items.extend(_dict_items(value))
    structured = node.output.get("structured_output")
    if isinstance(structured, dict):
        for key in (
            "media_items",
            "mediaItems",
            "characterItems",
            "sceneItems",
            "storyboardItems",
            "storyboardVideoItems",
            "items",
            "characters",
            "scenes",
            "shots",
            "segments",
        ):
            items.extend(_dict_items(structured.get(key)))
    return items


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _item_id(item: dict[str, Any]) -> str | None:
    return _first_text(
        item.get("item_id"),
        item.get("itemId"),
        item.get("id"),
        item.get("scene_id"),
        item.get("sceneId"),
        item.get("character_id"),
        item.get("characterId"),
        item.get("shot_id"),
        item.get("shotId"),
        item.get("segment_id"),
        item.get("segmentId"),
        item.get("entity_id"),
        item.get("entityId"),
    )


def _item_semantic_type(node: WorkflowGraphNode, item: dict[str, Any]) -> str:
    return _first_text(item.get("semantic_type"), item.get("item_type"), item.get("type")) or {
        "character-generation": "character",
        "scene-generation": "scene",
        "storyboard": "storyboard_shot",
        "storyboard-video-generation": "storyboard_video_segment",
        "bgm": "bgm",
    }.get(node.node_type, "workflow_node")


def _item_display_name(item_id: str | None, item: dict[str, Any]) -> str | None:
    return _first_text(item.get("display_name"), item.get("title"), item.get("name"), item_id)


def _find_graph_asset(graph: WorkflowGraph, asset_id: str | None) -> dict[str, Any] | None:
    if not asset_id:
        return None
    for node in graph.nodes:
        for asset in _node_assets(node):
            if str(asset.get("asset_id") or "") == asset_id:
                item = dict(asset)
                item.setdefault("node_id", node.id)
                item.setdefault("source_node_id", node.id)
                return item
    return None


def _node_assets(node: WorkflowGraphNode) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for value in (node.output_assets, node.output.get("assets"), node.output.get("output_assets")):
        assets.extend(_dict_items(value))
    candidates = node.output.get("candidate_assets")
    assets.extend(_dict_items(candidates))
    return assets


def _find_canvas_asset(
    data_dir: Path, workflow_id: str, asset_id: str | None
) -> dict[str, Any] | None:
    if not asset_id:
        return None
    for asset in load_canvas_assets(data_dir, workflow_id):
        if str(asset.get("asset_id") or "") == asset_id:
            return dict(asset)
    return None


def _find_library_asset(settings: Settings, asset_id: str | None) -> dict[str, Any] | None:
    if not asset_id:
        return None
    service = AssetLibraryService(settings)
    try:
        summaries = service.list_entities(include_archived=False).entities
    except AssetLibraryError:
        return None
    for summary in summaries:
        try:
            detail = service.get_entity(summary.entity_id, include_archived=False)
        except AssetLibraryError:
            continue
        for asset in detail.assets:
            if asset.asset_id != asset_id:
                continue
            source = dict(detail.entity.source or {})
            return {
                **asset.model_dump(mode="json"),
                "source_type": "asset_library",
                "library_entity_id": detail.entity.entity_id,
                "entity_type": detail.entity.entity_type,
                "display_name": detail.entity.display_name,
                "node_id": source.get("node_id"),
                "source_node_id": source.get("node_id"),
                "item_id": source.get("entity_id"),
                "entity_id": source.get("entity_id") or detail.entity.entity_id,
                "workflow_id": source.get("workflow_id"),
            }
    return None


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
