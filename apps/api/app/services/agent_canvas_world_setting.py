"""Deterministic World Setting proposal adaptation and rendering."""

from __future__ import annotations

from typing import Mapping

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_world_setting import (
    WorldSettingContextAudienceV2,
)


WORLD_SETTING_AUDIENCE_BY_CREATIVE_ROLE: dict[str, WorldSettingContextAudienceV2] = {
    "script": "script",
    "product": "product",
    "prop": "prop",
    "character": "character",
    "scene": "scene",
    "storyboard_sequence": "storyboard",
    "storyboard_video": "video",
    "bgm": "bgm",
}


class WorldSettingBindingPolicy:
    """Derive trusted context routing from the target creative role."""

    def audience_for_role(self, creative_role: str) -> WorldSettingContextAudienceV2:
        audience = WORLD_SETTING_AUDIENCE_BY_CREATIVE_ROLE.get(creative_role)
        if audience is None:
            raise V2PersistenceError(
                "world_setting_target_unsupported",
                "Target Node role does not support World Setting context.",
                stage="world_setting_binding_policy",
            )
        return audience

    def metadata_for_target(
        self,
        creative_role: str,
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        supplied = {
            key: value
            for key, value in dict(metadata or {}).items()
            if key
            not in {
                "projection_audience",
                "projection_contract_version",
                "projection_snapshot_id",
            }
        }
        return {
            **supplied,
            "context_kind": "world_setting",
            "semantic_reference_role": "world_setting_reference",
            "target_audience": self.audience_for_role(creative_role),
            "context_contract_version": "world-setting-context-v2",
        }
