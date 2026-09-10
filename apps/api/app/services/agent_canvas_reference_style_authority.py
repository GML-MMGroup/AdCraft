"""Conditional reference-style authority for Character Main and Scene Main."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from app.schemas.agent_canvas_role_prompt_preparation import RolePromptPreparationContextV2
from app.schemas.agent_canvas_reference_conditioning import ReferenceConditioningPlanV1
from app.schemas.agent_canvas_reference_style import (
    ReferencePromptProvenanceV1,
    ReferenceStyleAuthorityPolicyV1,
)


_CHARACTER_PROTECTED = (
    "identity",
    "face_and_hair",
    "silhouette_and_proportions",
    "accessories",
    "medium",
    "linework",
    "palette",
    "shading",
    "texture",
    "shape_language",
    "wardrobe",
)
_SCENE_PROTECTED = (
    "environment_identity",
    "architecture",
    "materials",
    "lighting",
    "atmosphere",
    "medium",
    "linework",
    "palette",
    "shading",
    "texture",
    "shape_language",
    "spatial_layout",
)


class ReferenceStyleAuthorityPolicyResolver:
    """Resolve style authority only from one exact current role Binding."""

    def resolve(
        self, context: RolePromptPreparationContextV2
    ) -> ReferenceStyleAuthorityPolicyV1 | None:
        if context.role_variant == "character_main":
            expected = ("character", "identity_guidance")
            reference_kind = "character_main"
            protected = _CHARACTER_PROTECTED
        elif context.role_variant == "scene_board":
            expected = ("scene", "environment_guidance")
            reference_kind = "scene_main"
            protected = _SCENE_PROTECTED
        else:
            return None
        if len(context.bindings) != 1:
            return None
        binding = context.bindings[0]
        if (
            binding.source_role != expected[0]
            or binding.reference_purpose != expected[1]
            or binding.asset_id is None
            or binding.asset_version_id is None
            or binding.source_node_id is None
            or binding.source_node_revision is None
        ):
            return None
        raw_overrides = context.explicit_controls.get("visual_overrides", {})
        overrides = (
            tuple(sorted(str(key) for key in raw_overrides if str(key) in protected))
            if isinstance(raw_overrides, Mapping)
            else ()
        )
        control_level = "provider_instruction"
        policy_payload = {
            "reference_kind": reference_kind,
            "protected_dimensions": protected,
            "explicit_override_dimensions": overrides,
            "reference_control_level": control_level,
            "binding_id": binding.binding_id,
            "asset_id": binding.asset_id,
            "asset_version_id": binding.asset_version_id,
            "binding_revision": binding.binding_revision,
            "source_node_revision": binding.source_node_revision,
        }
        digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(policy_payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        return ReferenceStyleAuthorityPolicyV1(
            policy_id=f"reference-style:{reference_kind}:{binding.binding_id}",
            policy_version="reference_style_authority_v1",
            reference_kind=reference_kind,
            semantic_reference_role=expected[0] + "_reference",
            reference_purpose=expected[1],
            protected_dimensions=protected,
            explicit_override_dimensions=overrides,
            reference_control_level=control_level,
            policy_digest=digest,
            provenance=ReferencePromptProvenanceV1(
                binding_id=binding.binding_id,
                binding_revision=binding.binding_revision,
                asset_id=binding.asset_id,
                asset_version_id=binding.asset_version_id,
                source_node_id=binding.source_node_id,
                source_node_revision=binding.source_node_revision,
            ),
        )


class ReferenceAwareAssetPromptRenderer:
    """Render bounded reference authority without parsing free-form text."""

    def render(
        self,
        prompt: str,
        style_projection: str | None,
        policy: ReferenceStyleAuthorityPolicyV1,
        *,
        explicit_controls: Mapping[str, Any] | None = None,
        conditioning_plan: ReferenceConditioningPlanV1 | None = None,
    ) -> str:
        parts = [prompt.strip()]
        controls = explicit_controls or {}
        raw_overrides = controls.get("visual_overrides", {})
        if conditioning_plan is not None:
            parts.append(
                "Reference conditioning ("
                + conditioning_plan.reference_label
                + "): use this as the primary "
                + conditioning_plan.target_role.replace("_", " ")
                + " identity/style reference."
            )
            parts.append(
                "Preserve protected dimensions: "
                + ", ".join(conditioning_plan.protected_dimensions)
                + "."
            )
            parts.append(
                "Allowed changes: " + ", ".join(conditioning_plan.allowed_change_dimensions) + "."
            )
        else:
            parts.append(
                "Selected reference image is authoritative for protected visual dimensions: "
                + ", ".join(policy.protected_dimensions)
                + "."
            )
        if isinstance(raw_overrides, Mapping):
            values = [
                f"{key}={raw_overrides[key]}"
                for key in policy.explicit_override_dimensions
                if key in raw_overrides
            ]
            if values:
                parts.append("Explicit visual overrides: " + "; ".join(values) + ".")
        if conditioning_plan is not None:
            parts.append("Do not substitute an unrelated subject or environment.")
        return "\n\n".join(part for part in parts if part)


def resolve_reference_control_level(capability: Mapping[str, Any] | None) -> str:
    """Use native reference controls only when the selected capability declares one."""

    if capability and (
        capability.get("supports_native_reference_style") is True
        or capability.get("supports_native_reference_strength") is True
    ):
        return "native"
    return "provider_instruction"
