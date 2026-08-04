"""Authoritative Character and Scene target policy for V2 Agent interactions."""

from __future__ import annotations

from typing import Literal

from app.core.config import Settings
from app.schemas.agent_runtime import V2AgentTargetCatalog, V2ResolvedAgentTarget
from app.schemas.workflow_v2 import (
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
    WorkflowV2ChatActionTarget,
)
from app.services.v2_asset_locator import V2AssetLocatorError, V2AssetLocatorResolver
from app.services.v2_workflow_authoring import create_workflow_authoring_runtime


_NODE_POLICY = {
    "character-generation": (
        "character",
        "character_main_image",
        "character_three_view",
    ),
    "scene-generation": (
        "scene",
        "scene_main_image",
        "scene_multi_view_grid",
    ),
}


class V2AgentTargetResolutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class V2AgentTargetResolver:
    """Resolve only active Character and Scene targets from canonical authoring."""

    def __init__(self, settings: Settings) -> None:
        self._read_model = create_workflow_authoring_runtime(settings.media_data_dir).read_model
        self._asset_locator = V2AssetLocatorResolver(settings.media_data_dir)

    def list_active_targets(self, workflow_id: str) -> V2AgentTargetCatalog:
        workflow = self._load_workflow(workflow_id)
        targets = [
            self._resolved_from_item(
                workflow,
                item,
                target_type="item",
                target_locator=f"item:{item.item_id}",
            )
            for node in workflow.nodes
            if node.node_id in _NODE_POLICY
            for item in node.items
            if item.lifecycle_state == "active"
        ]
        return V2AgentTargetCatalog(
            workflow_id=workflow.workflow_id,
            state_version=self._state_version(workflow),
            targets=targets,
        )

    def resolve(
        self,
        workflow_id: str,
        target: WorkflowV2ChatActionTarget,
        *,
        requested_scope: Literal["main", "multiview"] | None = None,
    ) -> V2ResolvedAgentTarget:
        workflow = self._load_workflow(workflow_id)
        locator = target.locator
        if locator:
            kind, value = self._parse_locator(locator)
            if kind == "item":
                item = self._find_item(workflow, value)
                resolved = self._resolved_from_item(
                    workflow,
                    item,
                    target_type="item",
                    target_locator=locator,
                )
            elif kind == "slot":
                resolved = self._resolve_slot(workflow, value, locator)
            elif kind == "asset":
                asset_id, version_id = self._parse_asset_value(value)
                resolved = self._resolve_asset(
                    workflow,
                    asset_id,
                    version_id,
                    locator,
                )
            else:
                self._unsupported()
        elif target.target_type == "node":
            resolved = self._resolve_node(workflow, target.node_id)
        elif target.target_type == "slot":
            resolved = self._resolve_slot(
                workflow,
                target.slot_id,
                f"slot:{target.slot_id or ''}",
            )
        elif target.target_type == "asset":
            resolved = self._resolve_asset(
                workflow,
                target.asset_id,
                target.version_id,
                self._asset_target_locator(target.asset_id, target.version_id),
            )
        else:
            self._unsupported()

        scope = requested_scope or "main"
        if scope == "main":
            return resolved.model_copy(update={"requested_scope": "main"})
        multiview_slot_id = resolved.related_multiview_slot_id
        if not multiview_slot_id:
            self._unsupported()
        multiview_slot = self._find_slot(workflow, multiview_slot_id)
        if multiview_slot is None:
            self._unsupported()
        return resolved.model_copy(
            update={
                "target_locator": f"slot:{multiview_slot.slot_id}",
                "target_type": "slot",
                "slot_id": multiview_slot.slot_id,
                "slot_type": multiview_slot.slot_type,
                "requested_scope": "multiview",
                "asset_id": multiview_slot.selected_asset_id,
                "version_id": multiview_slot.selected_version_id,
            }
        )

    def _resolve_node(
        self,
        workflow: WorkflowV2,
        node_id: str | None,
    ) -> V2ResolvedAgentTarget:
        if node_id not in _NODE_POLICY:
            self._unsupported()
        node = next((node for node in workflow.nodes if node.node_id == node_id), None)
        if node is None:
            self._not_found()
        items = [item for item in node.items if item.lifecycle_state == "active"]
        if len(items) != 1:
            raise V2AgentTargetResolutionError(
                "agent_target_clarification_required",
                "Choose one exact Character or Scene item.",
            )
        return self._resolved_from_item(
            workflow,
            items[0],
            target_type="node",
            target_locator=f"node:{node_id}",
        )

    def _resolve_slot(
        self,
        workflow: WorkflowV2,
        slot_id: str | None,
        locator: str,
    ) -> V2ResolvedAgentTarget:
        slot = self._find_slot(workflow, slot_id)
        if slot is None:
            self._not_found()
        policy = _NODE_POLICY.get(slot.node_id)
        if policy is None or slot.slot_type != policy[1]:
            self._unsupported()
        item = self._find_item(workflow, slot.item_id)
        return self._resolved_from_item(
            workflow,
            item,
            target_type="slot",
            target_locator=locator,
        )

    def _resolve_asset(
        self,
        workflow: WorkflowV2,
        asset_id: str | None,
        version_id: str | None,
        locator: str,
    ) -> V2ResolvedAgentTarget:
        if not asset_id:
            self._not_found()
        try:
            located = self._asset_locator.resolve(workflow.workflow_id, locator)
        except V2AssetLocatorError as error:
            raise V2AgentTargetResolutionError(
                "agent_target_not_found",
                "The requested Agent target was not found.",
            ) from error
        if located.owner_node_id not in _NODE_POLICY or not located.owner_slot_id:
            self._unsupported()
        slot = self._find_slot(workflow, located.owner_slot_id)
        if slot is None:
            self._not_found()
        policy = _NODE_POLICY[located.owner_node_id]
        if (
            slot.slot_type != policy[1]
            or slot.selected_asset_id != located.asset_id
            or slot.selected_version_id != located.version_id
            or (version_id is not None and version_id != located.version_id)
        ):
            self._unsupported()
        item = self._find_item(workflow, slot.item_id)
        resolved = self._resolved_from_item(
            workflow,
            item,
            target_type="asset",
            target_locator=locator,
        )
        return resolved.model_copy(
            update={
                "asset_id": located.asset_id,
                "version_id": located.version_id,
            }
        )

    def _resolved_from_item(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2 | None,
        *,
        target_type: Literal["node", "item", "slot", "asset"],
        target_locator: str,
    ) -> V2ResolvedAgentTarget:
        if item is None or item.lifecycle_state != "active":
            self._not_found()
        policy = _NODE_POLICY.get(item.node_id)
        if policy is None:
            self._unsupported()
        owner_type, main_slot_type, multiview_slot_type = policy
        main_slot = next(
            (slot for slot in item.slots if slot.slot_type == main_slot_type),
            None,
        )
        if main_slot is None:
            self._not_found()
        multiview_slot = next(
            (slot for slot in item.slots if slot.slot_type == multiview_slot_type),
            None,
        )
        selected_locator = (
            self._asset_target_locator(
                main_slot.selected_asset_id,
                main_slot.selected_version_id,
            )
            if main_slot.selected_asset_id and main_slot.selected_version_id
            else None
        )
        return V2ResolvedAgentTarget(
            workflow_id=workflow.workflow_id,
            state_version=self._state_version(workflow),
            target_locator=target_locator,
            target_type=target_type,
            node_id=item.node_id,
            item_id=item.item_id,
            slot_id=main_slot.slot_id,
            slot_type=main_slot.slot_type,
            owner_type=owner_type,
            display_name=item.display_name,
            asset_id=main_slot.selected_asset_id,
            version_id=main_slot.selected_version_id,
            selected_main_asset_locator=selected_locator,
            related_multiview_slot_id=(
                multiview_slot.slot_id if multiview_slot is not None else None
            ),
        )

    def _load_workflow(self, workflow_id: str) -> WorkflowV2:
        try:
            return self._read_model.assemble(workflow_id)
        except Exception as error:
            raise V2AgentTargetResolutionError(
                "agent_target_not_found",
                "The requested Agent target was not found.",
            ) from error

    @staticmethod
    def _state_version(workflow: WorkflowV2) -> int:
        if workflow.state_version is None:
            raise V2AgentTargetResolutionError(
                "agent_target_revision_unavailable",
                "Workflow state version is unavailable.",
            )
        return workflow.state_version

    @staticmethod
    def _find_item(workflow: WorkflowV2, item_id: str | None) -> WorkflowItemV2 | None:
        return next(
            (item for node in workflow.nodes for item in node.items if item.item_id == item_id),
            None,
        )

    @staticmethod
    def _find_slot(workflow: WorkflowV2, slot_id: str | None) -> WorkflowSlotV2 | None:
        return next(
            (
                slot
                for node in workflow.nodes
                for item in node.items
                for slot in item.slots
                if slot.slot_id == slot_id
            ),
            None,
        )

    @staticmethod
    def _parse_locator(locator: str) -> tuple[str, str]:
        if ":" not in locator:
            raise V2AgentTargetResolutionError(
                "agent_target_not_found",
                "The requested Agent target was not found.",
            )
        kind, value = locator.split(":", 1)
        if not value:
            raise V2AgentTargetResolutionError(
                "agent_target_not_found",
                "The requested Agent target was not found.",
            )
        return kind, value

    @staticmethod
    def _parse_asset_value(value: str) -> tuple[str, str | None]:
        asset_id, separator, version_id = value.partition("@")
        if not asset_id or (separator and not version_id):
            raise V2AgentTargetResolutionError(
                "agent_target_not_found",
                "The requested Agent target was not found.",
            )
        return asset_id, version_id or None

    @staticmethod
    def _asset_target_locator(asset_id: str | None, version_id: str | None) -> str:
        if not asset_id:
            return "asset:"
        return f"asset:{asset_id}@{version_id}" if version_id else f"asset:{asset_id}"

    @staticmethod
    def _not_found() -> None:
        raise V2AgentTargetResolutionError(
            "agent_target_not_found",
            "The requested Agent target was not found.",
        )

    @staticmethod
    def _unsupported() -> None:
        raise V2AgentTargetResolutionError(
            "agent_target_not_supported",
            "Only Character and Scene main targets are supported.",
        )
