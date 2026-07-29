"""Semantic-role registry and structured Draft validation for Agent Canvas."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_ad_media import (
    AdMediaRoleContractV2,
    BgmContentV2,
    DesignAssetContentV2,
    ReferenceRequirementV2,
    SceneDesignBoardContentV2,
    StoryboardGridContentV2,
    VideoSegmentContentV2,
)


@dataclass(frozen=True, slots=True)
class _RegisteredRole:
    contract: AdMediaRoleContractV2
    content_model: type[BaseModel] | None


class AdMediaRoleRegistry:
    """Resolve one immutable advertising contract per semantic role."""

    def __init__(self) -> None:
        self._roles = _role_registry()

    def get(self, semantic_role: str) -> AdMediaRoleContractV2:
        registered = self._roles.get(semantic_role)
        if registered is None:
            raise _error("invalid_semantic_role", "Semantic role is not registered.")
        return registered.contract

    def validate_node_type(self, node_type: str, semantic_role: str) -> None:
        contract = self.get(semantic_role)
        if contract.node_type != node_type:
            raise _error(
                "semantic_role_node_type_mismatch",
                "Semantic role is incompatible with the node type.",
            )

    def validate_structured_content(
        self,
        semantic_role: str,
        content: dict[str, object],
    ) -> BaseModel | None:
        registered = self._roles.get(semantic_role)
        if registered is None:
            raise _error("invalid_semantic_role", "Semantic role is not registered.")
        if registered.content_model is None:
            return None
        try:
            return registered.content_model.model_validate(content)
        except ValidationError as error:
            code = {
                "scene_design_board": "scene_design_board_contract_invalid",
                "storyboard_grid": "storyboard_grid_contract_invalid",
            }.get(semantic_role, "invalid_role_content")
            raise _error(code, "Structured role content is invalid.") from error


class AdMediaDraftValidationService:
    """Validate role compatibility without rewriting creative prose."""

    def __init__(self, registry: AdMediaRoleRegistry | None = None) -> None:
        self._registry = registry or AdMediaRoleRegistry()

    def validate(
        self,
        *,
        node_type: str,
        semantic_role: str,
        structured_content: dict[str, object],
    ) -> AdMediaRoleContractV2:
        self._registry.validate_node_type(node_type, semantic_role)
        self._registry.validate_structured_content(
            semantic_role,
            structured_content,
        )
        return self._registry.get(semantic_role)


def _role_registry() -> dict[str, _RegisteredRole]:
    roles: dict[str, _RegisteredRole] = {}

    def add(
        role: str,
        node_type: str,
        media_type: str,
        model: type[BaseModel] | None = None,
        requirements: tuple[ReferenceRequirementV2, ...] = (),
    ) -> None:
        roles[role] = _RegisteredRole(
            contract=AdMediaRoleContractV2(
                semantic_role=role,
                node_type=node_type,
                output_media_type=media_type,
                content_schema_ref=model.__name__ if model else "FreeformContentV2",
                reference_requirements=requirements,
            ),
            content_model=model,
        )

    for role in ("creative_brief", "generation_brief", "generic_text"):
        add(role, "text", "text")
    add("advertising_script", "script", "text")
    for role in ("generic_image", "uploaded_image"):
        add(role, "image", "image")
    for role in (
        "product_main",
        "prop_main",
        "character_main",
    ):
        add(role, "image", "image", DesignAssetContentV2)
    for role, required_role in (
        ("product_view_board", "product_main"),
        ("character_turnaround", "character_main"),
    ):
        add(
            role,
            "image",
            "image",
            DesignAssetContentV2,
            (
                ReferenceRequirementV2(
                    binding_kind="image_reference",
                    required_role=required_role,
                    minimum=1,
                    maximum=1,
                ),
            ),
        )
    add("scene_design_board", "image", "image", SceneDesignBoardContentV2)
    add("storyboard_grid", "image", "image", StoryboardGridContentV2)
    for role in ("generic_video", "uploaded_video"):
        add(role, "video", "video")
    add(
        "storyboard_video_segment",
        "video",
        "video",
        VideoSegmentContentV2,
        (
            ReferenceRequirementV2(
                binding_kind="image_reference",
                required_role="storyboard_grid",
                minimum=1,
                maximum=1,
            ),
        ),
    )
    for role in ("generic_audio", "uploaded_audio"):
        add(role, "audio", "audio")
    add("bgm", "audio", "audio", BgmContentV2)
    add("final_composition", "editing", "video")
    return roles


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="ad_media_role_registry")
