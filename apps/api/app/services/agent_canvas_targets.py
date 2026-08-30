"""Workflow-scoped Agent Canvas target and locator resolution."""

from __future__ import annotations

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    AgentTargetRefV2,
    AgentTargetResolutionV2,
)
from app.services.agent_canvas_assets import AgentCanvasAssetService


class AgentCanvasTargetService:
    """Resolve public node and image-asset locators against canonical state."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        assets: AgentCanvasAssetService,
    ) -> None:
        self._workflows = workflows
        self._assets = assets

    def resolve(self, workflow_id: str, locator: str) -> AgentTargetResolutionV2:
        kind, target_id, version_id = _parse_locator(locator)
        if kind == "node":
            node = self._workflows.get_node(workflow_id, target_id)
            target = AgentTargetRefV2(
                kind="node",
                target_id=node.node_id,
                locator=f"node:{node.node_id}",
                display_name=node.title,
                node_type=node.node_type,
                creative_role=node.creative_role,
            )
        else:
            if version_id is None:
                raise _error(
                    "asset_reference_version_required",
                    "Asset locators require an immutable version identity.",
                )
            asset = self._assets.resolve_target_asset_version(
                workflow_id,
                target_id,
                version_id,
            )
            if asset.media_type != "image":
                raise _error(
                    "target_type_not_supported",
                    "Only image assets can be Agent targets.",
                )
            target = AgentTargetRefV2(
                kind="image_asset",
                target_id=asset.asset_id,
                locator=f"asset:{asset.asset_id}@{asset.version_id}",
                display_name=asset.display_name,
                media_type="image",
                asset_version_id=asset.version_id,
            )
        return AgentTargetResolutionV2(workflow_id=workflow_id, target=target)


def _parse_locator(locator: str) -> tuple[str, str, str | None]:
    if ":" not in locator:
        raise _error("locator_invalid", "Locator must contain a target kind.")
    kind, target_id = locator.split(":", 1)
    if kind not in {"node", "asset"} or not target_id.strip():
        raise _error("locator_invalid", "Locator is invalid.")
    normalized = target_id.strip()
    if kind == "node":
        return kind, normalized, None
    if "@" not in normalized:
        return kind, normalized, None
    asset_id, version_id = normalized.split("@", 1)
    if not asset_id or not version_id:
        raise _error("locator_invalid", "Locator is invalid.")
    return kind, asset_id, version_id


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_target_resolution")
