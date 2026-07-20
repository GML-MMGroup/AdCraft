from typing import Any

from app.core.config import Settings
from app.schemas.ad_workflow import AdWorkflowGenerateRequest
from app.schemas.workflow_graph import WorkflowGraphNode
from app.schemas.workflow_nodes import WorkflowNodeRunRequest, WorkflowRunRequest
from app.services.workflow_state import load_active_node_results


class WorkflowRunInputBuilder:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def load_active_results(self, workflow_id: str) -> dict[str, dict[str, Any]]:
        return load_active_node_results(self._settings.media_data_dir, workflow_id)

    def build_node_request(
        self,
        workflow_id: str,
        node_type: str,
        request: WorkflowRunRequest,
        active: dict[str, dict[str, Any]],
    ) -> WorkflowNodeRunRequest:
        raw_active = active.get(node_type)
        if raw_active and raw_active.get("input_context"):
            return WorkflowNodeRunRequest(
                workflow_id=workflow_id,
                node_id=node_type,
                node_type=node_type,
                input_context=raw_active.get("input_context", {}),
                input_assets=raw_active.get("input_assets", []),
                mode=self._node_run_mode(),
                media_mode=self._settings.media_mode,
                force_rerun=True,
                asset_references=request.asset_references,
                library_entity_ids=request.library_entity_ids,
                reference_mode=request.reference_mode,
                provider=request.provider,
                allow_provider_fallback=request.allow_provider_fallback,
                provider_hints=request.provider_hints,
            )

        return WorkflowNodeRunRequest(
            workflow_id=workflow_id,
            node_id=node_type,
            node_type=node_type,
            input_context=self.input_context_from_active(node_type, active),
            input_assets=self.input_assets_from_active(node_type, active, None),
            mode=self._node_run_mode(),
            media_mode=self._settings.media_mode,
            force_rerun=True,
            asset_references=request.asset_references,
            library_entity_ids=request.library_entity_ids,
            reference_mode=request.reference_mode,
            provider=request.provider,
            allow_provider_fallback=request.allow_provider_fallback,
            provider_hints=request.provider_hints,
        )

    def build_planned_node_request(
        self,
        *,
        workflow_id: str,
        node_type: str,
        request: WorkflowRunRequest,
        active: dict[str, dict[str, Any]],
        ad_request: AdWorkflowGenerateRequest | None,
        graph_node: WorkflowGraphNode | None,
    ) -> WorkflowNodeRunRequest:
        return WorkflowNodeRunRequest(
            workflow_id=workflow_id,
            node_id=node_type,
            node_type=node_type,
            input_context=self.graph_input_context(node_type, active, graph_node),
            input_assets=self.graph_input_assets(node_type, active, ad_request, graph_node),
            mode=self._node_run_mode(),
            media_mode=self._settings.media_mode,
            force_rerun=True,
            override_prompt=graph_node.override_prompt if graph_node else None,
            asset_references=request.asset_references,
            library_entity_ids=request.library_entity_ids,
            reference_mode=request.reference_mode,
            provider=request.provider,
            allow_provider_fallback=request.allow_provider_fallback,
            provider_hints=request.provider_hints,
        )

    def build_graph_node_request(
        self,
        *,
        workflow_id: str,
        node_type: str,
        request: WorkflowRunRequest,
        graph_node: WorkflowGraphNode,
    ) -> WorkflowNodeRunRequest:
        node_request = WorkflowNodeRunRequest(
            workflow_id=workflow_id,
            node_id=graph_node.id,
            node_type=node_type,
            input_context=seed_context_from_graph_node(graph_node),
            input_assets=graph_node.input_assets,
            mode=self._node_run_mode(),
            media_mode=self._settings.media_mode,
            force_rerun=True,
            override_prompt=graph_node.override_prompt,
            auto_resolve=True,
            asset_references=request.asset_references,
            library_entity_ids=request.library_entity_ids,
            reference_mode=request.reference_mode,
            provider=request.provider,
            allow_provider_fallback=request.allow_provider_fallback,
            provider_hints=request.provider_hints,
        )
        return node_request.model_copy(update={"defer_graph_updates": True})

    def graph_input_context(
        self,
        node_type: str,
        active: dict[str, dict[str, Any]],
        graph_node: WorkflowGraphNode | None,
    ) -> dict[str, Any]:
        context = self.input_context_from_active(node_type, active)
        if graph_node and graph_node.input_context:
            context.update(graph_node.input_context)
        return context

    def graph_input_assets(
        self,
        node_type: str,
        active: dict[str, dict[str, Any]],
        ad_request: AdWorkflowGenerateRequest | None,
        graph_node: WorkflowGraphNode | None,
    ) -> list[dict[str, Any]]:
        assets = self.input_assets_from_active(node_type, active, ad_request)
        if graph_node and graph_node.input_assets:
            seen = {str(asset.get("asset_id") or "") for asset in assets}
            for asset in graph_node.input_assets:
                asset_id = str(asset.get("asset_id") or "")
                if not asset_id or asset_id not in seen:
                    assets.append(asset)
                    seen.add(asset_id)
        return assets

    def input_context_from_active(
        self,
        node_type: str,
        active: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        return input_context_for_node_type(node_type, active)

    def input_assets_from_active(
        self,
        node_type: str,
        active: dict[str, dict[str, Any]],
        ad_request: AdWorkflowGenerateRequest | None,
    ) -> list[dict[str, Any]]:
        upstream_map = {
            "storyboard": ["product-generation", "character-generation", "scene-generation"],
            "storyboard-video-generation": [
                "product-generation",
                "character-generation",
                "scene-generation",
                "storyboard",
            ],
            "final-composition": ["storyboard-video-generation"],
        }
        assets: list[dict[str, Any]] = []
        seen: set[str] = set()
        if ad_request is not None and node_type in {
            "storyboard-image-generation",
            "storyboard-video-generation",
        }:
            for asset in ad_request.selected_assets:
                asset_dict = asset.model_dump(mode="json")
                asset_dict["role"] = role_for_asset(asset_dict.get("asset_role"))
                asset_id = str(asset_dict.get("asset_id") or "")
                if asset_id and asset_id not in seen:
                    assets.append(asset_dict)
                    seen.add(asset_id)
        for upstream in upstream_map.get(node_type, []):
            for asset in active.get(upstream, {}).get("output_assets", []):
                if not isinstance(asset, dict):
                    continue
                asset_id = str(asset.get("asset_id") or "")
                if asset_id and asset_id not in seen:
                    assets.append(asset)
                    seen.add(asset_id)
        return assets

    def seed_context_from_graph_node(self, node: WorkflowGraphNode) -> dict[str, Any]:
        return seed_context_from_graph_node(node)

    def graph_node_as_active_result(self, node: WorkflowGraphNode) -> dict[str, Any]:
        return graph_node_as_active_result(node)

    def _node_run_mode(self) -> str:
        return "mock" if self._settings.agno_mock_mode else "real"


_INPUT_CONTEXT_DEPENDENCIES: dict[str, tuple[tuple[str, str], ...]] = {
    "script": (
        ("requirements", "requirements-analysis"),
        ("creative_direction", "creative-direction"),
        ("product_design", "product-design"),
    ),
    "character-generation": (("script", "script"),),
    "scene-generation": (("script", "script"),),
    "storyboard": (
        ("script", "script"),
        ("product_generation", "product-generation"),
        ("character_generation", "character-generation"),
        ("scene_generation", "scene-generation"),
    ),
    "bgm": (
        ("script", "script"),
        ("storyboard", "storyboard"),
    ),
    "character-design": (
        ("requirements", "requirements-analysis"),
        ("creative_direction", "creative-direction"),
        ("script", "script"),
    ),
    "scene-design": (
        ("requirements", "requirements-analysis"),
        ("creative_direction", "creative-direction"),
        ("script", "script"),
    ),
    "character-image-generation": (("character_design", "character-design"),),
    "scene-image-generation": (("scene_design", "scene-design"),),
    "storyboard-image-generation": (
        ("storyboard", "storyboard"),
        ("script", "script"),
        ("character_design", "character-design"),
        ("scene_design", "scene-design"),
    ),
}


def input_context_for_node_type(
    node_type: str,
    active: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if node_type == "storyboard-video-generation":
        context = input_context_from_dependencies(
            active,
            (
                ("storyboard", "storyboard"),
                ("script", "script"),
                ("product_generation", "product-generation"),
                ("character_generation", "character-generation"),
                ("scene_generation", "scene-generation"),
            ),
        )
        context["duration_seconds"] = duration_from_script(active)
        return context
    if node_type == "final-composition":
        video_output = output(active, "storyboard-video-generation")
        return {
            "storyboard_video": video_output,
            "segments": video_output.get("segments", []) if isinstance(video_output, dict) else [],
            "bgm": output(active, "bgm"),
        }
    return input_context_from_dependencies(
        active,
        _INPUT_CONTEXT_DEPENDENCIES.get(node_type, ()),
    )


def input_context_from_dependencies(
    active: dict[str, dict[str, Any]],
    dependencies: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    return {context_key: output(active, node_type) for context_key, node_type in dependencies}


def output(active: dict[str, dict[str, Any]], node_type: str) -> dict[str, Any]:
    node_output = active.get(node_type, {}).get("output")
    return node_output if isinstance(node_output, dict) else {}


def duration_from_script(active: dict[str, dict[str, Any]]) -> int:
    script = output(active, "script")
    try:
        return int(script.get("duration_seconds") or 30)
    except (TypeError, ValueError):
        return 30


def role_for_asset(asset_role: Any) -> str:
    if asset_role == "product":
        return "product_reference"
    if asset_role == "character":
        return "character_reference"
    if asset_role == "scene":
        return "scene_reference"
    return "reference"


def graph_node_as_active_result(node: WorkflowGraphNode) -> dict[str, Any]:
    return {
        "workflow_id": node.workflow_id,
        "node_id": node.id,
        "node_type": node.node_type,
        "status": "completed",
        "output": node.output,
        "input_assets": node.input_assets,
        "output_assets": node.output_assets,
    }


def seed_context_from_graph_node(node: WorkflowGraphNode) -> dict[str, Any]:
    context: dict[str, Any] = {}
    resolved = node.input_context.get("resolved_input_context")
    if isinstance(resolved, dict):
        context.update(resolved)
    for key in (
        "requirements",
        "requirements_analysis",
        "product_design",
        "creative_direction",
        "script",
        "character_design",
        "scene_design",
        "storyboard",
        "duration_seconds",
        "aspect_ratio",
        "output_resolution",
    ):
        value = node.input_context.get(key)
        if key not in context and value not in (None, {}, []):
            context[key] = value
    return context
