"""Immutable connection and input-role policy for Agent Canvas authoring."""

from __future__ import annotations

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    CanvasBindingKindV2,
    CanvasConnectionDecisionV2,
    CanvasConnectionPolicyV2,
    CanvasConnectionRoleRuleV2,
    CanvasInputRoleV2,
    CanvasNodeTypeV2,
)


class AgentCanvasConnectionPolicyService:
    """Own the versioned, deterministic Canvas connection policy."""

    policy_version = "agent_canvas_connection_policy_v1"

    _target_node_types: dict[CanvasNodeTypeV2, tuple[CanvasNodeTypeV2, ...]] = {
        "text": ("text", "script"),
        "script": ("text", "script"),
        "image": ("text", "script", "image"),
        "video": ("text", "script", "image", "video", "audio", "editing"),
        "audio": ("text", "script"),
        "editing": ("video", "audio", "editing"),
    }
    _binding_kinds: dict[CanvasNodeTypeV2, CanvasBindingKindV2] = {
        "text": "text_context",
        "script": "text_context",
        "image": "image_reference",
        "video": "video_reference",
        "audio": "audio_reference",
        "editing": "video_reference",
    }
    _input_types = {
        "text": "text",
        "script": "text",
        "image": "image",
        "video": "video",
        "audio": "audio",
        "editing": "video",
    }
    _roles: dict[tuple[CanvasNodeTypeV2, CanvasNodeTypeV2], tuple[CanvasInputRoleV2, ...]] = {
        ("text", "text"): ("text_context",),
        ("text", "script"): ("text_context",),
        ("text", "image"): ("text_context",),
        ("text", "video"): ("text_context",),
        ("text", "audio"): ("text_context",),
        ("script", "text"): ("text_context",),
        ("script", "script"): ("text_context",),
        ("script", "image"): ("text_context",),
        ("script", "video"): ("text_context",),
        ("script", "audio"): ("text_context",),
        ("image", "image"): ("image_reference",),
        ("image", "video"): ("image_reference",),
        ("video", "video"): ("video_reference",),
        ("video", "editing"): ("video_reference",),
        ("audio", "video"): ("audio_reference",),
        ("audio", "editing"): ("audio_reference",),
        ("editing", "video"): ("video_reference",),
        ("editing", "editing"): ("video_reference",),
    }

    def public_policy(self) -> CanvasConnectionPolicyV2:
        return CanvasConnectionPolicyV2(
            policy_version=self.policy_version,
            target_node_types=self._target_node_types,
            input_roles=tuple(
                CanvasConnectionRoleRuleV2(
                    source_node_type=source,
                    target_node_type=target,
                    roles=roles,
                    default_role=roles[0],
                )
                for (source, target), roles in self._roles.items()
            ),
            image_asset_targets={
                "image": ("image_reference",),
                "video": ("image_reference",),
            },
            binding_kind_by_source_type=self._binding_kinds,
            model_validation={"explicit_model": "authoring_and_run", "automatic_model": "run"},
        )

    def decide(
        self,
        *,
        source_node_type: CanvasNodeTypeV2,
        target_node_type: CanvasNodeTypeV2,
        input_role: CanvasInputRoleV2 | None,
        is_image_asset: bool = False,
    ) -> CanvasConnectionDecisionV2:
        roles = self._roles.get((source_node_type, target_node_type), ())
        if is_image_asset and source_node_type == "image":
            roles = self.public_policy().image_asset_targets.get(target_node_type, ())
        if not roles:
            return CanvasConnectionDecisionV2(
                accepted=False,
                error_code="canvas_connection_incompatible",
                source_node_type=source_node_type,
                target_node_type=target_node_type,
            )
        normalized_role = input_role or roles[0]
        if normalized_role not in roles:
            return CanvasConnectionDecisionV2(
                accepted=False,
                error_code="canvas_input_role_invalid",
                source_node_type=source_node_type,
                target_node_type=target_node_type,
                input_role=normalized_role,
                allowed_roles=roles,
            )
        return CanvasConnectionDecisionV2(
            accepted=True,
            source_node_type=source_node_type,
            target_node_type=target_node_type,
            input_role=normalized_role,
            allowed_roles=roles,
            binding_kind=self._binding_kinds[source_node_type],
            input_type=self._input_types[source_node_type],
        )

    def require(
        self,
        *,
        source_node_type: CanvasNodeTypeV2,
        target_node_type: CanvasNodeTypeV2,
        input_role: CanvasInputRoleV2 | None,
        is_image_asset: bool = False,
    ) -> CanvasConnectionDecisionV2:
        decision = self.decide(
            source_node_type=source_node_type,
            target_node_type=target_node_type,
            input_role=input_role,
            is_image_asset=is_image_asset,
        )
        if decision.accepted:
            return decision
        error = V2PersistenceError(
            decision.error_code or "canvas_connection_incompatible",
            "Canvas connection is not compatible with the authoritative policy.",
            stage="agent_canvas_connection_policy",
        )
        error.details = {
            "policy_version": self.policy_version,
            "source_node_type": decision.source_node_type,
            "target_node_type": decision.target_node_type,
            "input_role": decision.input_role,
            "allowed_roles": list(decision.allowed_roles),
        }
        raise error
