"""Central versioned provider prompt compilation for Agent Canvas media roles."""

from __future__ import annotations

import hashlib
import json
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


@dataclass(frozen=True, slots=True)
class AgentCanvasPromptRegistration:
    semantic_role: str
    registry_ref: str
    boundary: str
    negative_boundary: str
    registry_digest: str


_ROLE_BOUNDARIES = {
    "product_main": (
        "Render one product identity with exact geometry, materials, marks, and proportions.",
        "Do not add people or a narrative environment unless explicitly declared.",
    ),
    "product_view_board": (
        "Render one view board of the exact bound product design without redesign.",
        "Do not alter geometry, materials, marks, proportions, palette, or style.",
    ),
    "prop_main": (
        "Render one isolated prop identity and material design.",
        "Do not add unrelated products, people, or narrative action.",
    ),
    "character_main": (
        "Render one character identity, wardrobe, silhouette, and neutral presentation.",
        "Do not add product placement or a narrative scene unless explicitly declared.",
    ),
    "character_turnaround": (
        "Render the exact bound individual as one consistent turnaround without redesign.",
        "Do not change face, hairstyle, wardrobe, silhouette, proportions, palette, or style.",
    ),
    "scene_design_board": (
        "Render one consistent environment as a complete 3x3 spatial design board.",
        "Do not progress narrative action across panels.",
    ),
    "storyboard_grid": (
        "Render one complete 3x3 storyboard grid for one coherent sequence.",
        "Do not generate captions, panel numbers, subtitles, speech bubbles, logos, or watermarks.",
    ),
    "storyboard_video_segment": (
        "Render one video segment from the complete bound storyboard grid.",
        "Do not generate background music; preserve declared dialogue, ambience, and effects.",
    ),
    "bgm": (
        "Render one instrumental background music track.",
        "No vocals, lyrics, speech, or spoken words.",
    ),
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
    ) -> CompiledProviderPromptV2:
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
        structured = self._roles.validate_structured_content(
            node.semantic_role,
            node.structured_content,
        )
        style = _style_from_content(structured)
        body = _render_content(structured)
        references = "\n".join(
            (
                f"- {item.binding_id}: asset={item.asset_id}; "
                f"media={item.media_type}; url={item.access_descriptor.media_url}"
            )
            for item in reference_bundle.references
        )
        prompt = "\n\n".join(
            part
            for part in (
                registration.boundary,
                f"Creative prompt:\n{node.generation_prompt or node.summary_prompt or ''}",
                f"Structured role content:\n{body}",
                f"Visual style ({style.source}):\n{style.style_prompt}",
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
        return "\n".join(
            [
                f"Sequence: {structured.sequence_summary}",
                *[
                    (
                        f"Panel {panel.panel_index}: {panel.beat}; {panel.composition}; "
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


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_provider_prompt_compiler")
