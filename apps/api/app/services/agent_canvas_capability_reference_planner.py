"""Deterministic guided reference planning for Agent Canvas capabilities."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol
import hashlib
import json

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    AgentCanvasWorkflowV2,
    CanvasNodeV2,
    ProjectAssetSummaryV2,
)
from app.schemas.agent_canvas_capabilities import (
    CapabilityReferencePlanV1,
    PlannedCapabilityReferenceV1,
)
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas_creative_session import GuidedSessionStateV2
from app.services.agent_canvas_capability_policy import CapabilityPolicyService
from app.services.agent_canvas_connection_policy import AgentCanvasConnectionPolicyService
from app.services.agent_canvas_role_reference_policy import (
    AgentCanvasRoleReferencePolicyService,
)


_CAPABILITY_ELEMENT = {
    "world_setting": "world_setting",
    "product_design": "product",
    "prop_design": "prop",
    "character_design": "character",
    "scene_design": "scene",
    "script_authoring": "script",
    "storyboard_design": "storyboard",
    "video_direction": "video",
    "bgm_direction": "audio",
}

_ROLE_CAPABILITY: dict[str, CapabilityIdV1] = {
    "world_setting": "world_setting",
    "product": "product_design",
    "prop": "prop_design",
    "character": "character_design",
    "scene": "scene_design",
    "script": "script_authoring",
    "storyboard_sequence": "storyboard_design",
    "storyboard_video": "video_direction",
    "bgm": "bgm_direction",
}

_SEMANTIC_ROLE = {
    "world_setting": "world_setting_reference",
    "product": "product_reference",
    "prop": "prop_reference",
    "character": "subject_reference",
    "scene": "environment_reference",
    "storyboard_sequence": "storyboard_visual_reference",
}

_AUTO_ROLE_PRIORITY: dict[CapabilityIdV1, dict[str, int]] = {
    "product_design": {"world_setting": 900},
    "prop_design": {"world_setting": 900},
    "character_design": {"world_setting": 900},
    "scene_design": {"world_setting": 900},
    "script_authoring": {"world_setting": 800},
    "storyboard_design": {
        "product": 100,
        "prop": 200,
        "character": 300,
        "scene": 400,
        "script": 500,
        "world_setting": 900,
    },
    "video_direction": {
        "storyboard_sequence": 0,
        "scene": 100,
        "character": 200,
        "product": 300,
        "prop": 400,
    },
    "bgm_direction": {"script": 100},
}

_REQUIRED_REFERENCE_ROLES: dict[CapabilityIdV1, frozenset[str]] = {
    "storyboard_design": frozenset(
        {"world_setting", "product", "prop", "character", "scene", "script"}
    ),
    "video_direction": frozenset({"storyboard_sequence"}),
}


class _ModelSelection(Protocol):
    def validate_selection(
        self,
        *,
        node_type: str,
        model_selection_mode: str,
        model_ref: str | None,
        parameters: Mapping[str, object] | None = None,
    ) -> object: ...


class CapabilityReferencePlanner:
    """Plan only explicit or selected guided sources, never arbitrary siblings."""

    def __init__(
        self,
        *,
        connection_policy: AgentCanvasConnectionPolicyService | None = None,
        model_selection: _ModelSelection | None = None,
    ) -> None:
        self._connections = connection_policy or AgentCanvasConnectionPolicyService()
        self._capabilities = CapabilityPolicyService()
        self._model_selection = model_selection
        self._role_references = AgentCanvasRoleReferencePolicyService()

    def plan(
        self,
        *,
        workflow: AgentCanvasWorkflowV2,
        session: GuidedSessionStateV2,
        capability_id: CapabilityIdV1,
        objective: str,
        explicit_node_ids: tuple[str, ...] = (),
        explicit_image_asset_ids: tuple[str, ...] = (),
        approved_node_ids: Mapping[str, tuple[str, ...]] | None = None,
        asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None = None,
        max_reference_images: int | None = None,
    ) -> CapabilityReferencePlanV1:
        del objective
        target_type = self._target_node_type(capability_id)
        role_policy = (
            self._role_references.for_capability(capability_id)
            if bool(getattr(session, "is_new_guided_production", False))
            else None
        )
        nodes = {node.node_id: node for node in workflow.nodes}
        selected_node_ids = tuple(
            dict.fromkeys(
                (
                    *self._selected_topic_node_ids(session),
                    *(
                        node_id
                        for role in sorted(approved_node_ids or {})
                        for node_id in (approved_node_ids or {})[role]
                    ),
                )
            )
        )
        selected_node_ids = self._preferred_automatic_character_references(
            selected_node_ids,
            nodes=nodes,
            capability_id=capability_id,
        )
        candidates: list[PlannedCapabilityReferenceV1] = []

        for order, node_id in enumerate(explicit_node_ids):
            node = nodes.get(node_id)
            if node is None:
                raise _error("Mentioned Node does not belong to the current workflow.")
            reference = self._node_reference(
                node=node,
                target_type=target_type,
                priority=order,
                explicit=True,
                required=self._required_reference(capability_id, node.creative_role),
                target_role=(role_policy.target_role if role_policy is not None else None),
            )
            if reference is not None:
                candidates.append(reference)

        for order, asset_id in enumerate(explicit_image_asset_ids):
            if asset_resolver is None:
                raise _error("Mentioned image asset cannot be resolved.")
            try:
                asset = asset_resolver(asset_id)
            except (KeyError, V2PersistenceError) as error:
                raise _error("Mentioned image asset is unavailable.") from error
            if (
                asset.project_id != workflow.project_id
                and asset.workflow_id != workflow.workflow_id
            ):
                raise _error("Mentioned image asset does not belong to the current project.")
            if asset.media_type != "image":
                raise _error("Mentioned asset is not an image reference.")
            decision = self._connections.decide(
                source_node_type="image",
                target_node_type=target_type,
                input_role="image_reference",
                is_image_asset=True,
            )
            if not decision.accepted:
                raise _error("Mentioned image asset is incompatible with the target capability.")
            candidates.append(
                PlannedCapabilityReferenceV1(
                    source_kind="image_asset",
                    source_id=asset.asset_id,
                    input_role="image_reference",
                    required=False,
                    default_selected=True,
                    semantic_reference_role=(
                        _SEMANTIC_ROLE.get(asset.source_semantic_role or "")
                        or (
                            asset.source_semantic_role
                            if asset.source_semantic_role in set(_SEMANTIC_ROLE.values())
                            else None
                        )
                    ),
                    priority=10 + order,
                    display_name=asset.display_name,
                    media_type="image",
                )
            )

        if capability_id != "quick_media":
            priorities = _AUTO_ROLE_PRIORITY.get(capability_id, {})
            for node_id in selected_node_ids:
                node = nodes.get(node_id)
                if node is None or node.creative_role not in priorities:
                    continue
                if not self._element_is_active(session, node.creative_role):
                    continue
                reference = self._node_reference(
                    node=node,
                    target_type=target_type,
                    priority=100 + priorities[node.creative_role],
                    explicit=False,
                    required=self._required_reference(capability_id, node.creative_role),
                    target_role=(role_policy.target_role if role_policy is not None else None),
                )
                if reference is not None:
                    candidates.append(reference)

        references, warnings = self._bounded(
            candidates,
            (
                max_reference_images
                if max_reference_images is not None
                else self._model_reference_limit(capability_id)
            ),
        )
        payload = {
            "capability_id": capability_id,
            "references": [item.model_dump(mode="json") for item in references],
            "warnings": list(warnings),
            "reference_policy_version": (
                role_policy.policy_version if role_policy is not None else None
            ),
        }
        digest = hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        return CapabilityReferencePlanV1(
            capability_id=capability_id,
            references=references,
            digest=digest,
            warnings=warnings,
        )

    def _target_node_type(self, capability_id: CapabilityIdV1) -> str:
        definition = self._capabilities.definition(capability_id)
        return definition.node_type or "video"

    @staticmethod
    def _preferred_automatic_character_references(
        node_ids: tuple[str, ...],
        *,
        nodes: Mapping[str, CanvasNodeV2],
        capability_id: CapabilityIdV1,
    ) -> tuple[str, ...]:
        if capability_id not in {"storyboard_design", "video_direction"}:
            return node_ids
        paired_turnarounds = {
            str(node.metadata.get("character_pair_id"))
            for node_id in node_ids
            if (node := nodes.get(node_id)) is not None
            and getattr(node, "creative_role", None) == "character"
            and getattr(node, "structured_content", {}).get("character_asset_kind") == "turnaround"
            and node.metadata.get("character_pair_id")
        }
        return tuple(
            node_id
            for node_id in node_ids
            if not (
                (node := nodes.get(node_id)) is not None
                and getattr(node, "creative_role", None) == "character"
                and getattr(node, "structured_content", {}).get("character_asset_kind")
                == "identity_master"
                and node.metadata.get("character_pair_id") in paired_turnarounds
            )
        )

    @staticmethod
    def _selected_topic_node_ids(session: GuidedSessionStateV2) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                node_id
                for topic in session.topics
                if topic.status == "selected"
                for node_id in topic.related_node_ids
            )
        )

    @staticmethod
    def _element_is_active(session: GuidedSessionStateV2, creative_role: str) -> bool:
        capability_id = _ROLE_CAPABILITY.get(creative_role)
        if capability_id is None:
            return False
        if any(
            topic.capability_id == capability_id and topic.status in {"deferred", "excluded"}
            for topic in session.topics
        ):
            return False
        element = _CAPABILITY_ELEMENT.get(capability_id)
        decisions = {
            decision.element_kind: decision.presence for decision in session.element_decisions
        }
        return decisions.get(element) != "exclude"

    def _node_reference(
        self,
        *,
        node,
        target_type: str,
        priority: int,
        explicit: bool,
        required: bool,
        target_role: str | None = None,
    ) -> PlannedCapabilityReferenceV1 | None:
        if target_role is not None:
            source_role = _policy_source_role(node)
            if (
                source_role is None
                or self._role_references.resolve(target_role).rule_for(source_role) is None
            ):
                if explicit:
                    raise _error("Mentioned Node is not allowed by the role reference policy.")
                return None
        input_role = (
            "text_context"
            if node.node_type in {"text", "script"}
            else {
                "image": "image_reference",
                "video": "video_reference",
                "audio": "audio_reference",
            }.get(node.node_type)
        )
        if input_role is None:
            return None
        decision = self._connections.decide(
            source_node_type=node.node_type,
            target_node_type=target_type,
            input_role=input_role,
        )
        if not decision.accepted:
            if explicit:
                raise _error("Mentioned Node is incompatible with the target capability.")
            return None
        return PlannedCapabilityReferenceV1(
            source_kind="node",
            source_id=node.node_id,
            input_role=input_role,
            required=required,
            default_selected=True,
            semantic_reference_role=_SEMANTIC_ROLE.get(node.creative_role),
            priority=priority,
            display_name=node.title,
            media_type="text" if node.node_type in {"text", "script"} else node.node_type,
        )

    @staticmethod
    def _required_reference(capability_id: CapabilityIdV1, creative_role: str) -> bool:
        return creative_role in _REQUIRED_REFERENCE_ROLES.get(capability_id, frozenset())

    def _bounded(
        self,
        candidates: list[PlannedCapabilityReferenceV1],
        max_reference_images: int | None,
    ) -> tuple[tuple[PlannedCapabilityReferenceV1, ...], tuple[str, ...]]:
        ordered = sorted(candidates, key=lambda item: (item.priority, item.source_id))
        unique: list[PlannedCapabilityReferenceV1] = []
        seen: set[tuple[str, str]] = set()
        for item in ordered:
            identity = (item.source_kind, item.source_id)
            if identity not in seen:
                unique.append(item)
                seen.add(identity)
        limit = (
            sum(item.media_type == "image" for item in unique)
            if max_reference_images is None
            else max_reference_images
        )
        image_count = 0
        accepted: list[PlannedCapabilityReferenceV1] = []
        warnings: list[str] = []
        for item in unique:
            if item.media_type != "image":
                accepted.append(item)
                continue
            if image_count < limit:
                accepted.append(item)
                image_count += 1
                continue
            if item.required:
                raise V2PersistenceError(
                    "guided_reference_model_incompatible",
                    "The selected model cannot consume a required guided reference.",
                    stage="capability_reference_planning",
                )
            warnings.append(f"optional_reference_omitted:{item.source_kind}:{item.source_id}")
        normalized = tuple(
            item.model_copy(update={"priority": index}) for index, item in enumerate(accepted)
        )
        return normalized, tuple(warnings)

    def _model_reference_limit(self, capability_id: CapabilityIdV1) -> int | None:
        if self._model_selection is None:
            return None
        selected = self._model_selection.validate_selection(
            node_type=self._target_node_type(capability_id),
            model_selection_mode="default",
            model_ref=None,
            parameters={},
        )
        metadata = getattr(selected, "capability_metadata", None)
        if not isinstance(metadata, Mapping):
            return 0
        limits = metadata.get("reference_limits")
        if not isinstance(limits, Mapping):
            return int(metadata.get("max_references", 0))
        return int(limits.get("image", 0))


def _error(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "capability_reference_plan_invalid",
        message,
        stage="capability_reference_planning",
    )


def _policy_source_role(node: CanvasNodeV2) -> str | None:
    if node.creative_role == "scene":
        return "scene_board"
    if node.creative_role == "prop":
        return "prop"
    if node.creative_role == "storyboard_sequence":
        return "storyboard_grid"
    if node.creative_role == "character":
        return (
            "character_turnaround"
            if node.structured_content.get("character_asset_kind") == "turnaround"
            else "character_main"
        )
    if node.creative_role == "product":
        return (
            "product_multiview"
            if node.structured_content.get("asset_kind") == "multi_view"
            else "product_main"
        )
    return None
