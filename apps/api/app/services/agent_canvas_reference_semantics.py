"""Canonical metadata policy for Agent Canvas references."""

from __future__ import annotations

from typing import cast

from app.schemas.agent_canvas_ad_media import (
    GuidedReferenceKindV1,
    GuidedReferencePurposeV1,
    ProviderReferenceInstructionV1,
)
from app.services.agent_canvas_world_setting import WorldSettingBindingPolicy


class AgentCanvasReferenceSemanticPolicy:
    """Normalize reference metadata without taking command ownership."""

    def external_metadata(
        self,
        *,
        source_role: str | None,
        target_role: str,
        semantic_reference_role: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        values = dict(metadata or {})
        if semantic_reference_role is not None:
            values["semantic_reference_role"] = semantic_reference_role
        if source_role == "world_setting" or semantic_reference_role == "world_setting_reference":
            return WorldSettingBindingPolicy().metadata_for_target(target_role, values)
        return values

    @staticmethod
    def character_pair_metadata(character_pair_id: str) -> dict[str, object]:
        return {
            "character_pair_id": character_pair_id,
            "reference_purpose": "identity_master",
            "semantic_reference_role": "subject_reference",
        }

    @staticmethod
    def product_pair_metadata() -> dict[str, object]:
        return {"semantic_reference_role": "subject_reference"}


_PROVIDER_REFERENCE_INSTRUCTIONS: dict[
    tuple[GuidedReferenceKindV1, GuidedReferencePurposeV1], str
] = {
    (
        "character_main",
        "identity_guidance",
    ): (
        "Use this image as the authoritative Character Main identity reference. "
        "Preserve identity, silhouette, wardrobe, and distinguishing design facts."
    ),
    (
        "scene_main",
        "environment_guidance",
    ): (
        "Use this image as the authoritative Scene Main environment reference. "
        "Preserve spatial layout, materials, lighting, and environmental identity."
    ),
}


def compile_provider_reference_instruction(
    *,
    reference_kind: object,
    reference_purpose: object,
) -> ProviderReferenceInstructionV1 | None:
    """Compile only validated guided-reference semantics for provider delivery."""

    if reference_kind is None and reference_purpose is None:
        return None
    if not isinstance(reference_kind, str) or not isinstance(reference_purpose, str):
        raise ValueError("provider_reference_instruction_invalid")
    key = (
        cast(GuidedReferenceKindV1, reference_kind),
        cast(GuidedReferencePurposeV1, reference_purpose),
    )
    instruction = _PROVIDER_REFERENCE_INSTRUCTIONS.get(key)
    if instruction is None:
        raise ValueError("provider_reference_instruction_invalid")
    return ProviderReferenceInstructionV1(
        reference_kind=key[0],
        semantic_purpose=key[1],
        instruction=instruction,
    )
