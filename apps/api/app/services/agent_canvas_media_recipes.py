"""Role-specific Agent Canvas media recipe validation and prompt adaptation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_ad_media import (
    AdReferenceBundleV2,
    BgmContentV2,
    CompiledProviderPromptV2,
    DesignAssetContentV2,
    ProviderModelCapabilityV2,
    SceneDesignBoardContentV2,
    StoryboardGridContentV2,
    VideoSegmentContentV2,
)
from app.services.agent_canvas_ad_media import AdMediaRoleRegistry
from app.services.agent_canvas_provider_prompts import (
    AgentCanvasProviderPromptCompiler,
)


@dataclass(frozen=True, slots=True)
class RecipeProviderResult:
    asset_id: str
    media_type: str


class _RecipeService:
    def __init__(
        self,
        compiler: AgentCanvasProviderPromptCompiler | None = None,
    ) -> None:
        self._roles = AdMediaRoleRegistry()
        self._compiler = compiler or AgentCanvasProviderPromptCompiler(self._roles)

    def _compile(
        self,
        node: CanvasNodeV2,
        bundle: AdReferenceBundleV2,
    ) -> CompiledProviderPromptV2:
        return self._compiler.compile(node, self._roles.get(node.semantic_role), bundle)


class SceneDesignBoardContractService(_RecipeService):
    def validate(
        self,
        content: SceneDesignBoardContentV2,
        references: AdReferenceBundleV2,
    ) -> None:
        explicit = set(content.explicit_entity_reference_ids)
        available = {
            identity
            for reference in references.references
            for identity in (reference.asset_id, reference.source_node_id)
            if identity
        }
        if not explicit.issubset(available):
            raise _error(
                "scene_design_board_contract_invalid",
                "Every explicit Scene entity must have an explicit image binding.",
            )

    def execute(
        self,
        node: CanvasNodeV2,
        references: AdReferenceBundleV2,
        provider: Callable[[CompiledProviderPromptV2, AdReferenceBundleV2], RecipeProviderResult],
    ) -> RecipeProviderResult:
        content = SceneDesignBoardContentV2.model_validate(node.structured_content)
        self.validate(content, references)
        return provider(self._compile(node, references), references)


class StoryboardGridContractService(_RecipeService):
    def execute(
        self,
        node: CanvasNodeV2,
        references: AdReferenceBundleV2,
        provider: Callable[[CompiledProviderPromptV2, AdReferenceBundleV2], RecipeProviderResult],
    ) -> RecipeProviderResult:
        StoryboardGridContentV2.model_validate(node.structured_content)
        return provider(self._compile(node, references), references)


class DesignAssetPromptService(_RecipeService):
    def execute(
        self,
        node: CanvasNodeV2,
        references: AdReferenceBundleV2,
        provider: Callable[[CompiledProviderPromptV2, AdReferenceBundleV2], RecipeProviderResult],
    ) -> RecipeProviderResult:
        DesignAssetContentV2.model_validate(node.structured_content)
        contract = self._roles.get(node.semantic_role)
        for requirement in contract.reference_requirements:
            matching = [
                item
                for item in references.references
                if item.source_semantic_role == requirement.required_role
            ]
            if len(matching) < requirement.minimum:
                raise _error(
                    "role_required_reference_missing",
                    "Required main-design binding is missing.",
                )
        return provider(self._compile(node, references), references)


class VideoSegmentPromptService(_RecipeService):
    def validate(
        self,
        content: VideoSegmentContentV2,
        capability: ProviderModelCapabilityV2,
    ) -> None:
        if (
            capability.max_duration_seconds is not None
            and content.duration_seconds > capability.max_duration_seconds
        ):
            raise _error(
                "video_duration_unsupported",
                "Requested video duration exceeds model capability.",
            )
        native_audio_required = any(
            (
                content.dialogue,
                content.voice_style,
                content.environment_sound,
                content.action_effects,
            )
        )
        if native_audio_required and not capability.supports_native_audio:
            raise _error(
                "video_native_audio_unsupported",
                "Selected video model cannot preserve required native audio.",
            )

    def render_prompt(
        self,
        node: CanvasNodeV2,
        references: AdReferenceBundleV2,
        capability: ProviderModelCapabilityV2,
    ) -> CompiledProviderPromptV2:
        content = VideoSegmentContentV2.model_validate(node.structured_content)
        self.validate(content, capability)
        return self._compile(node, references)


class BgmPromptService(_RecipeService):
    def validate(
        self,
        content: BgmContentV2,
        capability: ProviderModelCapabilityV2,
    ) -> None:
        if (
            capability.max_duration_seconds is not None
            and content.duration_seconds > capability.max_duration_seconds
        ):
            raise _error(
                "bgm_duration_unsupported",
                "Requested BGM duration exceeds model capability.",
            )

    def execute_optional(
        self,
        node: CanvasNodeV2,
        references: AdReferenceBundleV2,
        capability: ProviderModelCapabilityV2,
        provider: Callable[[CompiledProviderPromptV2, AdReferenceBundleV2], RecipeProviderResult],
    ) -> RecipeProviderResult | None:
        content = BgmContentV2.model_validate(node.structured_content)
        self.validate(content, capability)
        try:
            return provider(self._compile(node, references), references)
        except Exception:
            return None


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_media_recipe")
