"""Canonical metadata policy for Agent Canvas references."""

from __future__ import annotations

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
