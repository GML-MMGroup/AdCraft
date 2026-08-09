"""Central versioned provider prompt compilation for Agent Canvas media roles."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_ad_media import (
    AdMediaRoleContractV2,
    AdReferenceBundleV2,
    BgmContentV2,
    CompiledProviderPromptV2,
    DesignAssetContentV2,
    SceneDesignBoardContentV2,
    StoryboardGridContentV2,
    VideoSegmentContentV2,
    VisualStyleContractV2,
    resolve_visual_style,
)
from app.services.agent_canvas_ad_media import AdMediaRoleRegistry
from app.services.agent_canvas_creative_direction import CreativeDirectionService
from app.schemas.agent_canvas_world_setting import WorldSettingContextEnvelopeV2


@dataclass(frozen=True, slots=True)
class AgentCanvasPromptRegistration:
    semantic_role: str
    registry_ref: str
    boundary: str
    negative_boundary: str
    registry_digest: str


_ROLE_BOUNDARIES = {
    "product": (
        "Render one product identity with exact geometry, materials, marks, and proportions.",
        "Do not add people or a narrative environment unless explicitly declared.",
    ),
    "prop": (
        "Render one isolated prop identity and material design.",
        "Do not add unrelated products, people, or narrative action.",
    ),
    "character": (
        "Render one character identity, wardrobe, silhouette, and neutral presentation.",
        "Do not add product placement or a narrative scene unless explicitly declared.",
    ),
    "scene": (
        "Render one consistent environment as a complete 3x3 spatial design board.",
        "Do not progress narrative action across panels.",
    ),
    "storyboard_sequence": (
        "Render one complete 3x3 storyboard image for one coherent sequence. "
        "Keep all nine distinct frames in strict reading order with consistent "
        "identities, world details, visual style, and narrative continuity. "
        "Do not render labels or panel numbers anywhere in the image. Use visual "
        "storytelling without visible text in every frame.",
        "Do not generate captions, panel numbers, subtitles, speech bubbles, logos, or watermarks.",
    ),
    "storyboard_video": (
        "Render one video segment from the complete bound storyboard grid.",
        "Do not generate background music; preserve declared dialogue, ambience, and effects.",
    ),
    "bgm": (
        "Render one instrumental background music track.",
        "No vocals, lyrics, speech, or spoken words.",
    ),
    "general_image": (
        "Render one image from the saved Node prompt.",
        "Do not add undeclared identities or text.",
    ),
    "general_video": (
        "Render one video from the saved Node prompt and explicit Bindings.",
        "Do not add background music unless the prompt explicitly requests it.",
    ),
    "general_audio": (
        "Render one audio asset from the saved Node prompt.",
        "Do not add undeclared speech or lyrics.",
    ),
}
_STYLE_ROLE_BY_SEMANTIC_ROLE = {
    "product": "product",
    "prop": "prop",
    "character": "character",
    "scene": "scene",
    "storyboard_sequence": "storyboard",
    "storyboard_video": "video",
    "bgm": "bgm",
    "general_image": "quick_media",
    "general_video": "quick_media",
    "general_audio": "quick_media",
}
_WORLD_SETTING_ROLE_LABEL = {
    "product": "Product",
    "prop": "Prop",
    "character": "Character",
    "scene": "Scene",
    "storyboard": "Storyboard",
    "video": "Video",
    "bgm": "BGM",
}


def list_agent_canvas_prompt_registrations() -> tuple[AgentCanvasPromptRegistration, ...]:
    return tuple(
        _registration(role, boundary, negative)
        for role, (boundary, negative) in _ROLE_BOUNDARIES.items()
    )


class AgentCanvasProviderPromptCompiler:
    """Compile deterministic role prompts without an LLM or sibling context."""

    def __init__(self, roles: AdMediaRoleRegistry | None = None) -> None:
        self._roles = roles or AdMediaRoleRegistry()
        self._registrations = {
            item.semantic_role: item for item in list_agent_canvas_prompt_registrations()
        }

    def compile(
        self,
        node: CanvasNodeV2,
        role_contract: AdMediaRoleContractV2,
        reference_bundle: AdReferenceBundleV2,
        *,
        creative_direction_projection: Mapping[str, object] | None = None,
        world_setting: WorldSettingContextEnvelopeV2 | None = None,
    ) -> CompiledProviderPromptV2:
        if not str(node.generation_prompt or "").strip():
            raise _error(
                "node_prompt_empty",
                "A media Node requires a saved generation prompt before provider preparation.",
            )
        if role_contract.semantic_role != node.semantic_role:
            raise _error(
                "provider_prompt_contract_failed",
                "Node role does not match the prompt contract.",
            )
        registration = self._registrations.get(node.semantic_role)
        if registration is None:
            raise _error(
                "provider_prompt_contract_failed",
                "Provider prompt registration is missing.",
            )
        if creative_direction_projection is not None:
            CreativeDirectionService().validate_role_projection(
                _STYLE_ROLE_BY_SEMANTIC_ROLE[node.semantic_role],
                creative_direction_projection,
            )
        if world_setting is not None:
            expected_audience = _STYLE_ROLE_BY_SEMANTIC_ROLE[node.semantic_role]
            if world_setting.target_audience != expected_audience:
                raise _error(
                    "world_setting_context_audience_invalid",
                    "World Setting context audience does not match the target role.",
                )
        structured = self._roles.validate_structured_content(
            node.semantic_role,
            node.structured_content,
        )
        style = _style_from_content(structured)
        body = _render_content(structured)
        reference_identities = _render_reference_identities(reference_bundle)
        references = "\n".join(
            (
                f"- {item.binding_id}: asset={item.asset_id}; "
                f"media={item.media_type}; semantic_reference_role="
                f"{item.semantic_reference_role or 'unspecified'}; "
                f"url={item.access_descriptor.media_url}"
            )
            for item in reference_bundle.references
        )
        prompt = "\n\n".join(
            part
            for part in (
                registration.boundary,
                f"Creative prompt:\n{node.generation_prompt or node.summary_prompt or ''}",
                f"Structured role content:\n{body}",
                reference_identities,
                f"Visual style ({style.source}):\n{style.style_prompt}",
                _render_world_setting(world_setting) if world_setting is not None else "",
                f"Explicit references:\n{references}" if references else "",
            )
            if part
        )
        negative = "\n".join(
            (
                registration.negative_boundary,
                *style.negative_style_constraints,
            )
        )
        context = {
            "node_id": node.node_id,
            "node_revision": node.revision,
            "prompt_context_snapshot_id": node.prompt_context_snapshot_id,
            "role_contract_version": node.role_contract_version,
            "structured_content": node.structured_content,
            "world_setting_context": (
                {
                    "source_node_id": world_setting.source_node_id,
                    "source_node_revision": world_setting.source_node_revision,
                    "compiler_digest": world_setting.compiler_digest,
                    "context_digest": world_setting.context_digest,
                }
                if world_setting is not None
                else None
            ),
        }
        return CompiledProviderPromptV2(
            semantic_role=node.semantic_role,
            prompt_registry_ref=registration.registry_ref,
            prompt_registry_digest=registration.registry_digest,
            render_context_digest=_digest(context),
            prompt_digest=hashlib.sha256(prompt.encode()).hexdigest(),
            reference_bundle_digest=reference_bundle.bundle_digest,
            style_source=style.source,
            prompt=prompt,
            negative_prompt=negative,
            provider_parameters=_provider_parameters(node.semantic_role),
        )


def _registration(
    role: str,
    boundary: str,
    negative: str,
) -> AgentCanvasPromptRegistration:
    registry_ref = f"adcraft.agent_canvas.{role}.v1"
    return AgentCanvasPromptRegistration(
        semantic_role=role,
        registry_ref=registry_ref,
        boundary=boundary,
        negative_boundary=negative,
        registry_digest=hashlib.sha256(
            f"{registry_ref}\n{boundary}\n{negative}".encode()
        ).hexdigest(),
    )


def _style_from_content(structured: object) -> VisualStyleContractV2:
    style = getattr(structured, "style", None)
    return style if isinstance(style, VisualStyleContractV2) else resolve_visual_style()


def _render_content(structured: object) -> str:
    if isinstance(structured, SceneDesignBoardContentV2):
        return "\n".join(
            [
                f"Environment: {structured.scene_identity}",
                f"Layout: {structured.layout}",
                *[
                    (
                        f"Panel {panel.panel_index}: {panel.view_or_zone}; "
                        f"{panel.spatial_description}; {panel.lighting_material_detail}"
                    )
                    for panel in structured.panels
                ],
            ]
        )
    if isinstance(structured, StoryboardGridContentV2):
        frame_positions = (
            "Top-left frame",
            "Top-center frame",
            "Top-right frame",
            "Middle-left frame",
            "Center frame",
            "Middle-right frame",
            "Bottom-left frame",
            "Bottom-center frame",
            "Bottom-right frame",
        )
        return "\n".join(
            [
                f"Sequence: {structured.sequence_summary}",
                *[
                    (
                        f"{frame_positions[panel.panel_index - 1]} content: "
                        f"{panel.beat}; {panel.composition}; "
                        f"{panel.camera}; {panel.subject_action}; "
                        f"continuity={panel.continuity_from_previous}"
                    )
                    for panel in structured.panels
                ],
            ]
        )
    if isinstance(structured, VideoSegmentContentV2):
        return "\n".join(
            (
                f"Segment: {structured.segment_summary}",
                f"Duration: {structured.duration_seconds} seconds",
                f"Storyboard: {structured.storyboard_content}",
                f"Dialogue: {structured.dialogue}",
                f"Voice style: {structured.voice_style}",
                f"Environment sound: {structured.environment_sound}",
                f"Action effects: {structured.action_effects}",
            )
        )
    if isinstance(structured, BgmContentV2):
        return "\n".join(
            (
                f"Music: {structured.music_summary}",
                f"Duration: {structured.duration_seconds} seconds",
                f"Pace: {structured.pace}",
                f"Energy: {structured.energy_curve}",
                f"Instrumentation: {structured.instrumentation}",
                f"Mood: {structured.mood}",
            )
        )
    if isinstance(structured, DesignAssetContentV2):
        return f"Identity: {structured.subject_identity}\nDesign: {structured.design_summary}"
    if structured is None:
        return ""
    return json.dumps(structured.model_dump(mode="json"), sort_keys=True)


def _provider_parameters(semantic_role: str) -> dict[str, str | int | float | bool]:
    if semantic_role == "storyboard_sequence":
        return {"sequential_generation": False}
    return {}


def _render_world_setting(context: WorldSettingContextEnvelopeV2) -> str:
    parts = [
        "Authoritative World setting context "
        "(overrides conflicting model-authored details):\n"
        f"{context.shared_summary}"
    ]
    if context.relevant_world_rules:
        parts.append(
            "World rules:\n" + "\n".join(f"- {item}" for item in context.relevant_world_rules)
        )
    if context.relevant_visual_continuity:
        parts.append(
            "Visual continuity:\n"
            + "\n".join(f"- {item}" for item in context.relevant_visual_continuity)
        )
    return "\n\n".join(parts)


def _render_reference_identities(reference_bundle: AdReferenceBundleV2) -> str:
    identities = [
        {
            "binding_id": reference.binding_id,
            "source_role": reference.source_semantic_role,
            "semantic_reference_role": reference.semantic_reference_role,
            "facts": reference.source_identity_facts,
        }
        for reference in reference_bundle.references
        if reference.source_identity_facts
    ]
    if not identities:
        return ""
    return (
        "Authoritative bound reference identities:\n"
        "These persisted Binding facts override conflicting model-authored details. "
        "Keep their identities and environments unchanged while retaining creative "
        "freedom for panel action, composition, and camera.\n"
        + "\n".join(
            f"- {json.dumps(identity, sort_keys=True, ensure_ascii=True)}"
            for identity in identities
        )
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_provider_prompt_compiler")
